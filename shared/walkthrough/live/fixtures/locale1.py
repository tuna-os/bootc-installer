"""org.freedesktop.locale1 on the private system bus of the walkthrough."""

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """<node><interface name='org.freedesktop.locale1'>
<property name='Locale' type='as' access='read'/>
<property name='X11Layout' type='s' access='read'/>
<property name='X11Model' type='s' access='read'/>
<property name='X11Variant' type='s' access='read'/>
<property name='X11Options' type='s' access='read'/>
<property name='VConsoleKeymap' type='s' access='read'/>
<method name='SetLocale'><arg type='as' direction='in'/><arg type='b' direction='in'/></method>
<method name='SetX11Keyboard'><arg type='s' direction='in'/><arg type='s' direction='in'/>
<arg type='s' direction='in'/><arg type='s' direction='in'/><arg type='b' direction='in'/>
<arg type='b' direction='in'/></method></interface></node>"""
VALUES = {"Locale": GLib.Variant("as", ["LANG=en_US.UTF-8"]), "X11Layout": GLib.Variant("s", "us")}

bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
bus.register_object(
    "/org/freedesktop/locale1", Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0],
    lambda *a: a[-1].return_value(None),
    lambda *a: VALUES.get(a[4], GLib.Variant("s", "")), None)
Gio.bus_own_name_on_connection(bus, "org.freedesktop.locale1", 0, None, None)
GLib.MainLoop().run()
