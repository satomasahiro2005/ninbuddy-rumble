"""Replace the RawJoyConRumbleBridge class inside a target nxbt server.py with
the class defined in a source file.

Usage:
    python3 apply_patch.py <path/to/nxbt/controller/server.py> <source.py>

The source file may contain a comment header before the class; everything from
the first `class RawJoyConRumbleBridge():` line onward is used. The target must
already import Lock (`from threading import Thread, Lock`) and contain a
top-level `class ControllerServer():` immediately after the bridge class.
"""
import sys

server_path = sys.argv[1]
source_path = sys.argv[2]

server = open(server_path).read()
source = open(source_path).read()

marker = "class RawJoyConRumbleBridge():"
new_class = source[source.index(marker):].rstrip("\n")

assert "from threading import Thread, Lock" in server, \
    "target missing 'from threading import Thread, Lock'"

end_marker = "\n\nclass ControllerServer():"
i = server.index(marker)
j = server.index(end_marker)
assert i < j, "markers out of order in target"

server = server[:i] + new_class + server[j:]
open(server_path, "w").write(server)
print("RawJoyConRumbleBridge replaced OK")
