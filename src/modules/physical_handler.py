import pygame
import time
import glob
import os
import select
import struct

from modules import controller, input_maps
from threading import Thread

# store last movement time & joystick object
last_movement = 0
joystick = None
paddle_thread_started = False

# Xbox Elite paddles are exposed by Linux xpad as BTN_TRIGGER_HAPPY5-8
# instead of the ABXY buttons configured in the controller profile.
elite_paddle_map = {
    708: ["B"],
    709: ["A"],
    710: ["DPAD_UP"],
    711: ["DPAD_DOWN"]
}

PADDLE_DEBUG = False

def paddle_debug(message):
    if not PADDLE_DEBUG:
        return
    try:
        with open("/tmp/ninbuddy_paddles.log", "a") as log:
            log.write(f"{time.time():.3f} {message}\n")
    except OSError:
        pass

# update joystick values in packet
def update_joystick():
    global last_movement, joystick
    current_time = time.time()

    # if 120th of a second has passed, update joystick values
    if current_time - last_movement > 1/120:
        input_maps.axis_move(joystick)

        # update last movement time
        last_movement = current_time

def get_event_joystick_path():
    paths = sorted(glob.glob("/dev/input/by-id/*event-joystick"))
    if len(paths) > 0:
        return paths[0]

    try:
        with open("/proc/bus/input/devices") as devices:
            blocks = devices.read().split("\n\n")
    except OSError:
        return None

    for block in blocks:
        if "X-Box" not in block and "Xbox" not in block:
            continue
        for line in block.splitlines():
            if "Handlers=" not in line:
                continue
            for item in line.split():
                if item.startswith("event"):
                    return "/dev/input/" + item
    return None

def listen_elite_paddles():
    global paddle_thread_started
    path = get_event_joystick_path()
    if path is None:
        paddle_debug("no event joystick found")
        paddle_thread_started = False
        return

    event_size = struct.calcsize("llHHI")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        paddle_debug(f"listener opened {path}")
    except OSError as err:
        paddle_debug(f"listener failed {err}")
        paddle_thread_started = False
        return

    try:
        while controller.is_physical_connected:
            ready, _, _ = select.select([fd], [], [], 0.5)
            if not ready:
                continue

            try:
                data = os.read(fd, event_size * 32)
            except BlockingIOError:
                continue

            for offset in range(0, len(data) // event_size * event_size, event_size):
                _, _, event_type, code, value = struct.unpack(
                    "llHHI", data[offset:offset + event_size])

                if event_type != 1 or code not in elite_paddle_map:
                    continue

                paddle_debug(f"event code={code} map={elite_paddle_map[code]} value={value}")
                controller.update_packet(elite_paddle_map[code], value != 0)
    finally:
        os.close(fd)
        paddle_thread_started = False

def start_paddle_listener():
    global paddle_thread_started
    if paddle_thread_started:
        return

    paddle_thread_started = True
    paddle_debug("starting listener thread")
    paddle_thread = Thread(target=listen_elite_paddles)
    paddle_thread.daemon = True
    paddle_thread.start()

# connect physical controller
def connect_physical():
    global joystick

    # if physical controller is already connected, ignore
    if controller.is_physical_connected:
        return
    
    # initialise the connected physical controller
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    
    # update controller name & physical connection status
    controller.name = joystick.get_name()
    controller.is_physical_connected = True
    start_paddle_listener()
    
    # if mobile device isn't in-use, use physical controller
    if not controller.is_mobile_connected:
        conn = Thread(target=controller.connect)
        conn.daemon = True
        conn.start()

# listen for physical controller input
def listen():
    global last_movement, joystick

    # initialise pygame for easy access to joystick input
    pygame.init()

    # if physical controller is already connected, connect to switch
    if pygame.joystick.get_count() >= 1:
        connect_physical()
    
    # consistently check for input changes
    while True:

        # if physical controller is connected, update joystick each frame
        if controller.device != None:
            if controller.is_physical_connected:
                update_joystick()
        
            # update input packet sent to switch each frame
            controller.set_input()

        # for each event in pygame event queue
        for event in pygame.event.get():
            try:
                # if new physical controller is added for the first time, connect to switch
                if event.type == pygame.JOYDEVICEADDED and pygame.joystick.get_count() == 1:
                    connect_physical()
                
                # if physical controller is removed, attempt to disconnect from switch
                elif event.type == pygame.JOYDEVICEREMOVED and pygame.joystick.get_count() == 0:
                    controller.name = None
                    joystick.quit()
                    controller.is_physical_connected = False
                    disconn = Thread(target=controller.attempt_disconnect)
                    disconn.daemon = True
                    disconn.start()
                
                # if controller button is pressed, update packet accordingly
                elif event.type == pygame.JOYBUTTONDOWN:
                    input_maps.button_down(event.button)
                
                # if controller button is released, update packet accordingly
                elif event.type == pygame.JOYBUTTONUP:
                    input_maps.button_up(event.button)
                
                # if controller dpad is moved, update packet accordingly
                elif event.type == pygame.JOYHATMOTION:
                    input_maps.dpad_move(event.value)

                # if ZL or ZR are pressed, update packet accordingly
                # these are triggers on xbox & ps, so apply if 75% or more is pressed
                elif event.type == pygame.JOYAXISMOTION:
                    input_maps.z_button_move(event.axis, event.value)

            except Exception:
                # ignore any errors that occur
                # prevents software from crashing
                pass

        # The generated Switch controller runs at 66Hz; pacing this loop keeps
        # CPU use down without adding meaningful controller latency.
        time.sleep(1 / 240)
