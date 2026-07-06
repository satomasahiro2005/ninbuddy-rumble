import nxbt, time, os
from modules import config

# start nxbt and get format for input packet
# input packet is sent to switch each frame
# queue is used to prevent packet loss - updates at 20hz
nx = nxbt.Nxbt()
packet = nx.create_input_packet()
packet_queue = {}

# variables containing current controller and its visual state
device = None
state = "Waiting for controller..."

# name of physical controller (e.g. "Xbox Series X Controller")
name = None

# variables that determine connection state
is_physical_connected = False
is_mobile_connected = False
is_disconnecting = False

# declare colours for console output
red = "\033[31m"
bold = "\033[1m"
green = "\033[32m"
reset = "\033[0m"

# ip of raspberry pi
ip = None

# directory to extract ninbuddy to
extract_dir = f"/home/{os.environ.get('SUDO_USER')}/ninbuddy"

# update state visible to user via dashboard & console
def update_state(new_state):
    global state
    state = new_state

    # clear console
    os.system("clear")

    # output header
    print(f"{red}{bold}### NinBuddy by Josh Lotriet{reset}")
    print(f"{green}{bold}### STARTED{reset}\n")
    print(f"{bold}> {state}{reset}\n")

    # instructions for user to connect to switch
    print("Go to 'Change Grip/Order' on your Switch to connect.")
    print("Next, plug in any controller to your Raspberry Pi.\n")

    # if ip is valid, output connection details for user
    if ip.decode().strip().startswith("192.168."):
        print("To use a mobile device as a controller...")
        print(f"Go to: {bold}http://{ip.decode().strip()}:{config.port}{reset} on your phone.\n")
    
    # how to exit software
    print("Press CTRL+C to exit.\n")

# update packet with new joystick values
def update_packet(location, value):
    global packet, packet_dirty

    # write only on real changes so set_input() can skip the expensive
    # cross-process push when nothing moved
    if len(location) == 1:
        if packet.get(location[0]) != value:
            packet[location[0]] = value
            packet_dirty = True

    # otherwise, access nested dict and update with value
    else:
        nested = packet[location[0]]
        if nested.get(location[1]) != value:
            nested[location[1]] = value
            packet_dirty = True

# release every input (used when the physical pad drops off USB so the
# virtual controller goes neutral instead of holding stale buttons)
def release_all():
    global packet
    for key, value in packet.items():
        if isinstance(value, dict):
            for sub in value:
                value[sub] = 0 if sub in ("X_VALUE", "Y_VALUE") else False
        elif isinstance(value, bool):
            packet[key] = False

packet_dirty = True
_last_push = 0.0

# add packet data to queue to prevent packet loss
def add_to_queue(location, value):
    global packet_queue

    # if click location isnt in queue yet, add it
    if location not in packet_queue:
        packet_queue[location] = {
            "queue": [value],
            "last_change": 0
        }
        return
    
    # otherwise, add value to queue
    packet_queue[location]["queue"] += [value]


# set input packet to values in packet
def set_input():
    # iterate through packet queue to update packet
    for button in packet_queue:
        queue = packet_queue[button]["queue"]
        last_change = packet_queue[button]["last_change"]

        # if queue is empty, ignore
        if len(queue) == 0:
            continue

        # if it hasn't been 1/20s since last change, ignore
        if time.time() - last_change < 1 / 20:
            continue

        # otherwise, update packet and last change
        packet_queue[button]["last_change"] = time.time()
        update_packet([button], queue[0])

        # remove first value from queue
        queue.pop(0)

    # update packet with new joystick values
    # NOTE: the push must stay unconditional -- gating it on packet changes
    # breaks held buttons downstream (observed on air: button frames lasted
    # a single report). Optimize elsewhere.
    nx.set_controller_input(device, packet)

# connect new generated controller to switch
def connect():
    global joystick, state, device, input_devices, is_disconnecting
    
    # already holding a virtual controller (e.g. the pad re-enumerated
    # after a USB blip): keep using it instead of creating a second one
    if device != None:
        return

    # if ready to connect, update states & connect via nxbt
    if not is_disconnecting:
        update_state("Connecting to console...")

        # Reconnect directly to the last console when one is remembered:
        # this skips the Change Grip/Order registration screen entirely.
        # NXBT falls back to normal pairing if the reconnect fails.
        reconnect_address = None
        try:
            with open("/etc/nxbt/last_switch") as f:
                value = f.read().strip().upper()
            if len(value) == 17 and value.count(":") == 5:
                reconnect_address = value
        except OSError:
            pass

        device = nx.create_controller(nxbt.PRO_CONTROLLER, frequency=120,
                                      reconnect_address=reconnect_address)
        nx.wait_for_connection(device)
        update_state("Connected to console!")

        # remember this console for the next start
        try:
            address = nx.state[device]["last_connection"]
            if address:
                with open("/etc/nxbt/last_switch", "w") as f:
                    f.write(str(address))
        except (KeyError, TypeError, OSError):
            pass

# attempt to disconnect from switch, if possible
def attempt_disconnect():
    global state, is_mobile_connected, is_physical_connected, device, input_devices, is_disconnecting, packet

    # reset packet to prevent infinite input, if user is still holding buttons
    packet = nx.create_input_packet()

    # if another device is still connected or is already disconnecting, ignore
    if is_mobile_connected or is_physical_connected or is_disconnecting:
        return
    
    # set disconnecting state and wait for connection to be removed
    is_disconnecting = True

    # while device isnt connected yet, wait
    while "Connected" not in state:
        time.sleep(0.1)

    # if connected but missing mobile/physical, disconnect from controller and update vars accordingly
    if device != None and not (is_mobile_connected or is_physical_connected):
        update_state("Disconnecting from console...")
        nx.remove_controller(device)
        device = None
        update_state("Waiting for controller...")
    
    # regardless, update disconnecting state
    is_disconnecting = False
