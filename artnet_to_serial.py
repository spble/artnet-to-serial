import socket
import sys
from artnet import packet
import serial
from serial.tools import list_ports
import struct
import threading
import queue
import itertools
import time

UDP_IP = "0.0.0.0"
UDP_PORT = 6454
try:
    SERIAL_DEVICE = next(serial.tools.list_ports.grep("")).device
except StopIteration:
    print("No serial devices found.")
    sys.exit(1)
BAUD_RATE = 500000



DEBUG = True

START_UNIVERSE = 1
MAX_UNIVERSES = 32
UNIVERSE_SIZE = 450
NUM_PIXELS = 4800
SKIP_UNIVERSE = [254] * UNIVERSE_SIZE
SEND_INCOMPLETE_FRAMES = False

PLAY_TEST_PATTERN = True
TEST_RED = [30,0,0] * NUM_PIXELS
TEST_GREEN = [0,30,0] * NUM_PIXELS
TEST_BLUE = [0,0,30] * NUM_PIXELS



class Listener(threading.Thread):

    def __init__(self,  output_queue, address=UDP_IP, port=UDP_PORT):

        super(Listener, self).__init__()

        self.queue = output_queue

        self.sock = socket.socket(socket.AF_INET, # Internet
                             socket.SOCK_DGRAM) # UDP
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((address, port))
        self.sock.settimeout(0.0)
        self.running = True
        print("Listening on %s:%s" % (address, port))

        self.clear_universes()


    def run(self):
        while(self.running):
            data, addr = self.read_artnet()
            if data is not None:
                pkt = packet.ArtNetPacket.decode(addr, data)
                if type(pkt) is packet.DmxPacket:
                    self.handle_artnet(pkt)

    def read_artnet(self):
        try:
            data, addr = self.sock.recvfrom(1024) # buffer size is 1024 bytes
            return data, addr
        except socket.error as e:
            return None, None

    def handle_artnet(self, pkt):
        self.universes[pkt.universe] = pkt.framedata[:UNIVERSE_SIZE]
        self.universes_received += 1
        self.universes_present |= (1 << pkt.universe)
        # Do it every N universes received
        #if self.universes_received == MAX_UNIVERSES:
        # Do it once all universes are received
        if self.universes_present == (2**MAX_UNIVERSES - 1):
            self.send_current_frame()
            self.clear_universes()

    def send_current_frame(self):
        # Get rid of any values of 254 or 255, as they have special meaning
        missed_universes = ['.'] * MAX_UNIVERSES
        incomplete_frame = False
        for index, universe in enumerate(self.universes):
            if universe is None:
                self.universes[index] = SKIP_UNIVERSE
                missed_universes[index] = 'X'
                incomplete_frame = True
                #print("Missed universe %d" % (index,))
            else:
                for n, c in enumerate(universe):
                    if c > 253:
                        self.universes[index][n] = 253
                        if DEBUG:
                            print("Channel Maxxed.")

        if not incomplete_frame and not SEND_INCOMPLETE_FRAMES:
            frame = bytearray(itertools.chain.from_iterable(self.universes))
            self.queue.put_nowait(frame)
            if DEBUG:
                print("Sent frame. (q: %d)\t%s\t(%f)" % (self.queue.qsize(),"".join(missed_universes), (self.universes_received/MAX_UNIVERSES)))
        else:
            if DEBUG:
                print("Skipped frame. (q: %d)\t%s" % (self.queue.qsize(),"".join(missed_universes)))

    def clear_universes(self):
        self.universes = [None,] * MAX_UNIVERSES
        self.universes_received = 0
        self.universes_present = 0


class Writer(threading.Thread):

    def __init__(self, input_queue, serial_device=SERIAL_DEVICE):

        super(Writer, self).__init__()

        self.queue = input_queue

        self.ser = serial.Serial(serial_device, BAUD_RATE, write_timeout=1)
        self.running = True
        print("Sending out to: %s" % (self.ser.name,))

    def run(self):
        while self.running:
            frame = self.queue.get()
            self.ser.write(frame)
            self.write_reset()
            self.queue.task_done()
            #print("QSize: %d" % (self.queue.qsize(),))

    def write_reset(self):
        self.ser.write(struct.pack("B", 255))
        self.ser.flushOutput()

    def write_test(self, test_frame=TEST_BLUE):
        self.ser.write(test_frame)
        self.write_reset()



if __name__ == '__main__':
    q = queue.Queue()

    w = Writer(q)
    w.daemon = True

    if PLAY_TEST_PATTERN:
        w.write_test(TEST_RED)
        time.sleep(0.5)
        w.write_test(TEST_GREEN)
        time.sleep(0.5)
        w.write_test(TEST_BLUE)
        time.sleep(0.5)

    l = Listener(q)
    l.daemon = True

    try:
        l.start()
        w.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        l.running = False
        w.running = False
        print("KeyboardInterrupt: Shutting down.")
        sys.exit(0)

