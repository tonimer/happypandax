﻿from gevent import monkey
monkey.patch_all()  # necessary to make these functions play nice with gevent

import uuid  # noqa: E402
import sys  # noqa: E402
import code  # noqa: E402

from inspect import getmembers, isfunction  # noqa: E402

from gevent import socket, pool  # noqa: E402
from gevent.server import StreamServer  # noqa: E402

from happypanda.common import constants, exceptions, utils, hlogger  # noqa: E402
from happypanda import interface  # noqa: E402
from happypanda.core import db, torrent, message  # noqa: E402
from happypanda.interface import meta, enums  # noqa: E402

log = hlogger.Logger(__name__)


def list_api():
    "Returns {name : object}"
    _special_functions = tuple()  # functions we don't consider as part of the api
    all_functions = []
    mods = utils.get_package_modules(interface)
    for m in mods:
        all_functions.extend(getmembers(m, isfunction))
    return {x[0]: x[1] for x in all_functions if not x[0]
            in _special_functions and not x[0].startswith('_')}

class Session:
    "Connection longevity"

    _sessions = set()

    def __init__(self, id=None):
        self._id = id if id else uuid.uuid4().hex
        self._expiration = None

    def extend(self):
        "Extend the life of this session"
        pass

    @classmethod
    def check(cls, session):
        "Check if session exists and is valid. Will raise error on expired session"
        if isinstance(session, Session):
            session = session._id

        if session:
            pass
        return False


class ClientHandler:
    "Handles clients"

    api = list_api()

    contexts = {} # session_id : context

    def __init__(self, client, address):
        self.errors = []
        self._client = client
        self._address = address
        self._ip = self._address[0]
        self._port = self._address[1]
        self._stopped = False
        self._accepted = False
        self.context = None
        self.session = None
        self.handshake()

    def get_context(self, user=None, password=None):
        "Creates or retrieves existing context object for this client"
        s = constants.db_session()
        user_obj = None
        if user or password:
            log.d("Client provided credentials, authenticating...")
            user_obj = s.query(
                db.User).filter(
                db.User.name == user).one_or_none()
            if user_obj:
                if not user_obj.password == password:
                    raise exceptions.AuthError(
                        utils.this_function(), "Wrong credentials")
            else:
                raise exceptions.AuthError(
                    utils.this_function(), "Wrong credentials")
        else:
            log.d("Client did not provide credentials")

            if not constants.disable_default_user:
                log.d("Authenticating with default user")
                user_obj = s.query(
                    db.User).filter(
                    db.User.role == db.User.Role.default).one()
            else:
                if not constants.allow_guests:
                    log.d("Guests are disallowed on this server")
                    raise exceptions.AuthRequiredError(utils.this_function())
                log.d("Authencticating as guest")
                user_obj = s.query(
                    db.User).filter(
                    db.and_op(
                        db.User.address == self._ip,
                        db.User.role == db.User.Role.guest)).one_or_none()
                if not user_obj:
                    user_obj = db.User(role=db.User.Role.guest)
                    s.add(user_obj)

        self.context = user_obj

        self.context.address = self._ip
        if not self.context.context_id:
            self.context.context_id = uuid.uuid4().hex

        self.context.config = None
        log.d("Client accepted")
        self._accepted = True

        s.commit()

    @staticmethod
    def sendall(client, msg):
        """
        Send data to client
        Params:
            client --
            msg -- bytes
        """
        assert isinstance(msg, bytes)

        log.d("Sending", sys.getsizeof(msg), "bytes to", client)
        client.sendall(msg)
        client.sendall(constants.postfix)

    def send(self, msg):
        """
        Wraps sendall
        """
        ClientHandler.sendall(self._client, msg)

    def parse(self, data):
        """
        Parse data from client
        Params:
            data -- data from client
        Returns:
            list of (function, function_kwargs, context_neccesity)
        """
        where = "Message parsing"
        log.d("Parsing incoming data")
        try:
            j_data = utils.convert_to_json(data, where)

            log.d("Check if required root keys are present")
            # {"name":name, "data":data, 'session':id}
            root_keys = ('name', 'data')
            self._check_both(where, "JSON dict", root_keys, j_data)
        except exceptions.ServerError as e:
            raise

        cmd = self._server_command(j_data)
        if cmd:
            return cmd

        if not self._accepted:
            self.handshake(j_data)
            return

        # 'data': [ list of function dicts ]
        function_keys = ('fname',)
        msg_data = j_data['data']
        if isinstance(msg_data, list):
            function_tuples = []
            for f in msg_data:
                try:
                    log.d("Cheking parameters in:", f)
                    self._check_missing(
                        where, "Function message", function_keys, f)
                except exceptions.InvalidMessage as e:
                    raise

                function_name = f['fname']
                try:
                    # check function
                    if function_name not in self.api:
                        e = exceptions.InvalidMessage(
                            where, "Function not found: '{}'".format(function_name))
                        self.errors.append((function_name, e))
                        continue

                    # check parameters
                    func_failed = False
                    func_args = tuple(
                        arg for arg in f if arg not in function_keys)
                    func_varnames = self.api[function_name].__code__.co_varnames
                    need_ctx = 'ctx' in func_varnames
                    for arg in func_args:
                        if arg not in func_varnames:
                            e = exceptions.InvalidMessage(
                                where, "Unexpected argument in function '{}': '{}'".format(
                                    function_name, arg))
                            self.errors.append((function_name, e))
                            func_failed = True
                            break
                    if func_failed:
                        continue

                    function_tuples.append(
                        (self.api[function_name], {
                            x: f[x] for x in func_args}, need_ctx))
                except exceptions.ServerError as e:
                    self.errors.append((function_name, e))

            return function_tuples
        else:
            raise exceptions.InvalidMessage(
                where, "No list of function objects found in 'data'")

    def _check_both(self, where, msg, keys, data):
        "Invokes both missing and unknown key"
        self._check_missing(where, msg, keys, data)
        self._check_unknown(where, msg, keys, data)

    def _check_unknown(self, where, msg, keys, data):
        "Checks if there are unknown keys in provided data"
        if len(data) != len(keys):
            self._check_required_key(
                where, "{} contains unknown key '{}'".format(
                    msg, "{}"), keys, data)

    def _expect_iterable(self, where, data):
        if not isinstance(data, (list, dict, tuple)):
            raise exceptions.InvalidMessage(
                where, "A list/dict was expected, not: {}".format(data))

    def _check_missing(self, where, msg, keys, data):
        "Check if required keys are missing in provided data"
        self._check_required_key(
            where, "{} missing '{}' key".format(
                msg, "{}"), data, keys)

    def _check_required_key(self, where, msg, required_keys, data):
        ""
        for y in (required_keys, data):
            self._expect_iterable(where, y)
        for x in data:
            if x not in required_keys:
                raise exceptions.InvalidMessage(where, msg.format(x))

    def _check_session(self, session_id):
        "Authenticate client with session"
        self._accepted = False

    def handshake(self, data=None):
        """
        Sends a welcome message
        """
        assert data is None or isinstance(data, dict)
        if isinstance(data, dict):
            log.d("Incoming handshake from client", self._address)
            data = data.get("data")
            if not constants.allow_guests:
                log.d("Guests are not allowed")
                self._check_both(
                    utils.this_function(), "JSON dict", ('user', 'password'), data)

            self.get_context(
                data.pop(
                    'user', None), data.pop(
                    'password', None))
            self.send(message.finalize("Authenticated"))
        else:
            log.d("Handshaking client:", self._address)
            msg = dict(
                version=meta.get_version().data(),
                guest_allowed=constants.allow_guests,
            )

            self.send(message.finalize(msg))

    def advance(self, buffer):
        """
        Advance the loop for this client
        Params:
            buffer -- data buffer to be parsed
        """
        try:
            if constants.server_ready:
                function_list = message.List("function", message.Function)
                functions = self.parse(buffer)
                if functions is None:
                    return
                if isinstance(functions, enums.ServerCommand):
                    if functions == enums.ServerCommand.RequestAuth:
                        self.handshake()
                    return functions

                for func, func_args, ctx in functions:
                    log.d("Calling function", func, "with args", func_args)
                    func_msg = message.Function(func.__name__)
                    try:
                        if ctx:
                            func_args['ctx'] = self.context
                            msg = func(**func_args)
                        else:
                            msg = func(**func_args)
                        assert isinstance(msg, message.CoreMessage) or None
                        func_msg.set_data(msg)
                    except exceptions.CoreError as e:
                        func_msg.set_error(message.Error(e.code, e.msg))
                    function_list.append(func_msg)

                # bad functions
                for fname, e in self.errors:
                    function_list.append(
                        message.Function(
                            fname, error=message.Error(
                                e.code, e.msg)))
                self.errors.clear()

                self.send(function_list.serialize())
            else:
                self.on_wait()
        except exceptions.CoreError as e:
            log.d("Sending exception to client:", e)
            self.on_error(e)

        except BaseException:
            if not constants.dev:
                log.exception("An unknown critical error has occurred")
                self.on_error(exceptions.HappypandaError(
                    "An unknown critical error has occurred"))  # TODO: include traceback
            else:
                raise

    def is_active(self):
        """
        Return bool indicating status of client
        """
        return not self._stopped

    def on_error(self, exception):
        """
        Creates and sends error message to client
        """
        assert isinstance(exception, exceptions.CoreError)
        e = message.Error(exception.code, exception.msg)
        self.send(e.serialize())

    def on_wait(self):
        """
        Sends wait message to client
        """
        self.send(message.Message("wait").serialize())

    def _server_command(self, data):
        d = data['data']
        if isinstance(d, str):

            if d.lower() == enums.ServerCommand.RequestAuth.value:
                return enums.ServerCommand.RequestAuth
            elif d.lower() == enums.ServerCommand.ServerQuit.value:  # TODO: check permission
                return enums.ServerCommand.ServerQuit
        return None


class HPServer:
    "Happypanda Server"

    def __init__(self):
        params = utils.connection_params()
        self._pool = pool.Pool(
            constants.allowed_clients if constants.allowed_clients else None)  # cannot be 0
        self._server = StreamServer(params, self._handle, spawn=self._pool)
        self._web_server = None
        self._clients = set()  # a set of client handlers

    def interactive(self):
        "Start an interactive session"
        api = locals().copy()
        api.pop("self")
        api.update(list_api())
        code.interact(
            banner="======== Start Happypanda Interactive ========",
            local=api)

    def _handle(self, client, address):
        "Client handle function"
        log.d("Client connected", str(address))
        handler = ClientHandler(client, address)
        self._clients.add(handler)
        try:
            buffer = b''
            while True:
                data, eof = utils.end_of_message(buffer)
                if eof:
                    buffer = data[1]
                    log.d("Received", sys.getsizeof(buffer), "bytes from ", address)
                    if handler.is_active():
                        client_msg = handler.advance(data[0])  # noqa: F841
                    else:
                        log.d("Client has disconnected", address)
                        break
                else:
                    log.d("Received data, EOF not reached. Waiting for more data from ", address)
                r = client.recv(constants.data_size)
                if not r:
                    log.d("Client has disconnected", address)
                    break
                else:
                    buffer += r
        except socket.error as e:
            log.exception("Client disconnected with error", e)
        finally:
            self._clients.remove(handler)
        log.d("Client disconnected", str(client), str(address))

    def _start(self, blocking=True):
        # TODO: handle db errors

        db.init()

        try:
            constants.server_started = True
            if blocking:
                log.i("Starting server... ({}:{}) (blocking)".format(
                    constants.host, constants.port), stdout=True)
                self._server.serve_forever()
            else:
                self._server.start()
        except (socket.error, OSError) as e:
            # include e
            log.exception(
                "Error: Failed to start server (Port might already be in use)")

    def run(self, interactive=False):
        """Run the server forever, blocking
        Params:
            interactive -- Start in interactive mode (Note: Does not work with web server)
        """
        tdaemon = torrent.start()
        try:
            self._start(not interactive)
            if interactive:
                self.interactive()
        except KeyboardInterrupt:
            pass
        self._server.stop()
        torrent.stop()
        tdaemon.join()
        log.i("Server shutting down.", stdout=True)


if __name__ == '__main__':
    server = HPServer()
    server.run()
