Using HappyPanda X
========================================


A default HPX installation has the following two components:

- **HappyPanda X Server**

    The backbone of everything. HPX and its associated clients and/or plugins won't function without this running.

- **HappyPanda X Webclient**

    The default frontend that comes with HPX. A web-based (JS) frontend for HPX, if you will.

    This component should also be running, even if you're not going to use the client.
    It should be started automatically on server start.

Setting up
-------------------------------------

Before starting HPX it is recommended to go through all the available settings that configure how HPX should be running.
You can see the available settings :ref:`here <Settings>`.

To use these settings, you create a configuration file named ``config.yaml`` in the root directory of HPX.

You can generate an example configuration file with all settings listed with their default values if you run this command: ``./happypandax --gen-config``.

.. note::
    - On a MacOS HPX installation, the root HPX folder is inside the bundle at ``HappyPanda X.app/Contents/MacOS/``.

    - On Windows the executable is named ``happypandax.exe`` (with ``.exe`` suffix).

Most of these settings can also be configured from a HPX client.

Starting
-------------------------------------

You can start up HPX in two ways with the executables named ``happypandax`` and ``happypandax_gui``.

The ``happypandax_gui`` executable is mostly just a GUI wrapper around ``happypandax`` to provide a user-friendly way of starting HPX.

Before starting, you can also see the available command-line arguments by supplying the ``--help`` argument to the ``happypandax`` executable on the cmd/terminal: ``./happypandax --help``.
You could also refer to :ref:`Command-Line Arguments`. 

To start the server (and the webclient with it) you just start one of the two executables.

.. note::
    On a MacOS HPX installation, the app bundle is set to invoke ``happypandax_gui`` on launch.


Migrating from HappyPanda
-------------------------------------

In the HPX root folder, you can find a command-line tool named ``HPtoHPX`` to help convert your HP database.
See available arguments by supplying the ``--help`` argument to the executable: ``./HPtoHPX --help``.

Convert your HP database like this: ``./HPtoHPX "path/to/old/file.db" "data/happypanda.db"``

Alternatively, you can also use the GUI wrapper ``happypandax_gui`` which provides a user-friendly way of doing it.

Using
-------------------------------------

After starting HPX you can start using it right away by opening up your browser and going to 
``localhost:7008`` *(replace ``7008`` with whatever port you chose the webclient server to listen on)*

What else you could do is look for another client to use HPX with. They can come in all forms (mobile apps, pc software, etc.) as long as someone builds it.
If you're interested in building a client to work with HPX, head over to :ref:`Creating frontends` for an introduction.

Since a HPX client cannot function without the server running, it is a good idea to always leave the HPX server running in the background.


Securing HappyPanda X
========================================

Users
-------------------------------------

HPX creates a default super-user called ``default`` with no password. This user is enabled by default.
If you're planning on having multiple people accessing your HPX server, or you want to access the server from a remote origin over the internet, it is best
you disable this user. Disable it with the setting ``server.disable_default_user``.

Additionally, you may also want to disallow people accessing the server without logging in with the settings ``server.allow_guests`` and ``server.require_auth``.

TLS/SSL Support
-------------------------------------

To enable SSL connections see the setting ``server.enable_ssl``.
You can choose to only enable SSL for one of the components by setting the value to either ``server`` or ``web``.
Set the value to ``true`` to enable for both.

Provide your certification and private key files with the settings ``server.server_cert`` and ``server.web_cert``.
If your private key and certificate is stored in the same file, you only need to set ``certfile`` and can ignore ``keyfile``.

You can also choose to not provide any certfiles at all, in which case HPX will proceed to create a self-signed certificate for your personal use.
These files can be found at ``[HPX]/data/certs/``. ``happypandax.crt`` is the certificate, ``happypandax.key`` is the private key and ``happypandax.pem`` is the combined version of the two.
To get other clients to accept your server with the self-signed certificate, provide them with the ``happypandax.crt`` file.

When using the self-signed certificate, browsers will complain about an unsecure connection. Since you're using HPX for personal reasons and trust yourself (i hope so), you can go
ahead and allow the connection by adding an exception.

.. note::
    If you have enabled SSL for the ``web`` component, do remember to access through the ``HTTPS`` protocol and not ``HTTP`` or you won't be able to connect.



Exposing HappyPanda X
========================================

To allow HPX to be accessed from your phone or other devices, you'll need to expose the server(s) to the private or public (internet) networks

.. todo::
    expose HPX

Private network
-------------------------------------

Doing this will allow for you to access HPX from *any device connected to your home network*

Public network
-------------------------------------

Doing this will allow for you to access HPX from *any device connected to the internet*

