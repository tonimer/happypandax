from src.react_utils import (h,
                             e,
                             createReactClass)
from src.ui import ui, LabelAccordion, TitleChange
from src.client import client, ServerMsg
from src.i18n import tr
from src import utils
from org.transcrypt.stubs.browser import __pragma__
__pragma__('alias', 'as_', 'as')

__pragma__('skip')
require = window = require = setInterval = setTimeout = setImmediate = None
clearImmediate = clearInterval = clearTimeout = this = document = None
JSON = Math = console = alert = requestAnimationFrame = None
__pragma__('noskip')


def set_key(e):
    this.setState({'key': e.target.value})
    this.props.on_change(this.props.idx, (e.target.value, this.state['value']))


def get_type(s):
    s = s.strip()
    # starwith and endswith doesn't work with tuple, transcrypt fault
    if s[0] in ("'", '"') and s[len(s) - 1] in ("'", '"'):
        return s[1:-1]
    elif s.lower() in ('none', 'null'):
        return None
    elif s.lower() == "true":
        return True
    elif s.lower() == "false":
        return False
    else:
        try:
            return int(s)
        except ValueError:
            return s


def set_value(e):
    value = e.target.value
    value = value.strip()
    if value.startswith('[') and value.endswith(']'):
        value = [
            get_type(x.strip()) for x in value.replace(
                '[', '').replace(
                ']', '').split(',') if x]
    elif value.startswith("{") and value.endswith("}"):
        value = value[1:-1]
        d = {}
        for kw in value.split(","):
            sp = kw.split(':')
            if len(sp) == 2:
                k, v = sp
                d[get_type(k)] = get_type(v)
        value = d

    if isinstance(value, str):
        value = get_type(value)
    this.setState({'value': value})
    this.props.on_change(this.props.idx, (this.state['key'], value))


ApiKwarg = createReactClass({
    'displayName': 'ApiKwarg',

    'getInitialState': lambda: {
        "key": "",
        "value": "",
    },

    'set_key': set_key,
    'set_value': set_value,

    'render': lambda: e(ui.Form.Group,
                        e(ui.Form.Input, js_name="param", label=tr(this, "ui.t-parameter", "Parameter"),
                          onChange=this.set_key, inline=True, width="6"),
                        e(ui.Form.Input, js_name="value", label=tr(this, "ui.t-value", "Value"),
                          onChange=this.set_value, inline=True, width="10"),
                        )
})


def handle_submit(ev):
    ev.preventDefault()
    this.setState({'calling': True})
    serv_data = {
        'fname': this.state['func_name']
    }

    def serv_rsponse(ctx, d, err):
        ctx.props.from_server(utils.syntax_highlight(JSON.stringify(d, None, 4)))
        ctx.setState({'calling': False})

    serv_data.update(this.state['kwargs'])
    msg = client.call(ServerMsg([serv_data], serv_rsponse, contextobj=this))
    this.props.to_server(utils.syntax_highlight(JSON.stringify(msg._msg['msg'], None, 4)))


__pragma__("jsiter")


def set_kwargs(i, v):
    k = {}
    this.state['params'][i] = v
    for i in this.state['params']:
        kv = this.state['params'][i]
        if kv[0].strip():
            k[kv[0]] = kv[1]

    this.setState({'kwargs': k})


__pragma__("nojsiter")


ApiForm = createReactClass({
    'displayName': 'ApiForm',

    'getInitialState': lambda: {
        "input_count": 1,
        "func_name": "",
        "params": {},
        "kwargs": {},
        "calling": False,
    },

    'set_func_name': lambda e: this.setState({'func_name': e.target.value}),

    'add_kwarg': lambda e, v: this.setState({'input_count': this.state['input_count'] + 1}),

    'set_kwargs': set_kwargs,

    'render_kwargs': lambda t: [e(ApiKwarg, idx=x, on_change=t.set_kwargs) for x in range(t.state['input_count'])],

    'handle_submit': handle_submit,

    'render': lambda: e(ui.Form,
                        e(ui.Form.Input, label=tr(this, "ui.t-function", "Function"), onChange=this.set_func_name),
                        *this.render_kwargs(this),
                        e(ui.Form.Group,
                            e(ui.Button, content=tr(this, "ui.b-add-parameter", "Add parameter"), onClick=this.add_kwarg),
                            e(ui.Form.Button, tr(this, "ui.b-call-function",
                                                 "Call function",), loading=this.state['calling']),
                          ),
                        onSubmit=this.handle_submit
                        )
})


def formatted_json(msg):
    return h('pre', dangerouslySetInnerHTML={'__html': msg}, className="overflow-auto")


Page = createReactClass({
    'displayName': 'ApiPage',

    'getInitialState': lambda: {
        "to_server": "",
        "from_server": "", },

    'componentWillMount': lambda: this.props.menu(None),

    'set_msg_to': lambda msg: this.setState({'to_server': msg}),
    'set_msg_from': lambda msg: this.setState({'from_server': msg}),

    'render': lambda: e(ui.Segment,
                        e(TitleChange, title="API"),
                        e(ui.Grid.Column,
                          e(ui.Message,
                            e(ui.Message.Header, tr(this, "ui.h-server-comm", "Server Communication")),
                            h(ui.Message.Content, tr(this, "ui.t-server-comm-tutorial", "..."),
                              style={"whiteSpace": "pre-wrap"}),
                            info=True,
                            ),
                          e(ui.Divider),
                          e(ApiForm, to_server=this.set_msg_to, from_server=this.set_msg_from),
                          e(ui.Divider),
                          e(LabelAccordion, formatted_json(this.state['to_server']),
                            label=tr(this, "ui.t-message", "Message"),
                            default_open=True),
                          e(LabelAccordion, formatted_json(this.state['from_server']),
                            label=tr(this, "ui.t-response", "Response"),
                            default_open=True, color="blue"),
                          ),
                        as_=ui.Container,
                        basic=True,
                        )
})
