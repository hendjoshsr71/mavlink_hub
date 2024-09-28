#!/usr/bin/env python3

# Plan
# Requirement: Receive Serial Data inside MAVLink  tunnel Packets then unpack it and send it over serial port
#  
# To Do:
# 1. Only check  and possibly MAVLink tunnel packets
# 2. Check timestamp to the MAVLink tunnel packets
#    - compute latency, jitter, etc.
#    - Log latency, jitter, dropped packets, etc.
#
# ArduPilot Firmware Side
# 1. Add timestamp to MAVLink tunnel packets
#
#
# Future:
# 1. Gather the serial port 
# 1. Add webpage to select the serial port and baudrate, etc.
#   - 
# 2. Add webpage to select the MAVLink tunnel type
# 
# IP address, port, and connection type UDP/TCP
# 
# Eventually:
# 1. Gather mavlink parameters from AP on the DSP
#   - Check which serial ports use ethernet bridge
#   - Set baud rate of python code to the same as the AP 
# 2, Create map for I/O ports between APP side and DSP (SLPI) side
#   - Serial
#       * Serial port 1 -> /dev/ttyHS1
#       * could be used to go serial to ethernet (however better to just use the usb ports for that. IE map the bridge to t)
#   - I2C
#   - USB ports: as a very litteral bridge the tunnel wouldn't be needed. Instead use the mav-router project
#   - SPI : could be used to go direct to a SPI to CAN transceiver 

# 1. Remove mavlink tunnel concept instead use IP address and port directly

from __future__ import print_function

from pymavlink import mavutil
import sys
import time
import threading
import struct

class Connection():
    def __init__(self, addr):
        self.addr = addr
        self._active = False
        self.last_packet_received = 0
        self.last_connection_attempt = 0

    def open(self):
        try:
            print("Opening connection to %s" % (self.addr,))
            self.mav = mavutil.mavlink_connection(self.addr, baud=57600)
            self._active = True
            self.last_packet_received = time.time() # lie

        except Exception as e:
            print("Connection to (%s) failed: %s" % (self.addr, str(e)))

    def close(self):
        self.mav.close()
        self._active = False

    def active(self):
        return self._active

class MAVLinkHub():
    def __init__(self, addrs, tlog=None):
        self.addrs = addrs
        self.conns = []
        self.connection_maintenance_target_should_live = True
        self.inactivity_timeout = 10
        self.reconnect_interval = 5
        self.tlog_filepath = tlog
        self.tlog = None

    def maintain_connections(self):
        now = time.time()
        for conn in self.conns:
            if not conn.active():
                continue
            if now - conn.last_packet_received > self.inactivity_timeout:
                print("Connection (%s) timed out" % (conn.addr,))
                conn.close()
        for conn in self.conns:
            if not conn.active():
                if now - conn.last_connection_attempt > self.reconnect_interval:
                    conn.last_connection_attempt = now
                    conn.open()
#            else:
#                print("Connection %s OK" % (conn.addr))
        time.sleep(0.1)

    def create_connections(self):
        for addr in self.addrs:
            print("Creating connection (%s)" % addr)
            self.conns.append(Connection(addr))

    def write_to_tlog(self, conn_index, m):
        # construct a timestamp which encodes the incoming link in the
        # bottom 3 bits of the value:
        timestamp = int(time.time() * 1.0e6)
        timestamp = timestamp & ~0b111
        if conn_index > 7:
            conn_index = 7
        timestamp |= conn_index
        self.tlog.write(bytearray(struct.pack('>Q', timestamp) + m.get_msgbuf()))

    def handle_messages(self):
        now = time.time()
        packet_received = False
        for (conn_index, conn) in enumerate(self.conns):
            if not conn.active():
                continue
            m = None
            try:
                m = conn.mav.recv_msg()
            except Exception as e:
                print("Exception receiving message on addr(%s): %s" % (str(conn.addr),str(e)))
                conn.close()

            if m is not None:
                conn.last_packet_received = now
                packet_received = True
#                print("Received message (%s) on connection %s from src=(%d/%d)" % (str(m), conn.addr, m.get_srcSystem(), m.get_srcComponent(),))
                for j in self.conns:
                    if not j.active():
                        continue
                    if j.addr == conn.addr:
                        continue
#                    print("  Resending message on connection %s" % (j.addr,))

                    # Only write out the correct MAVLink tunnel message type
                    #  
                    j.mav.write(m.get_msgbuf())

                if self.tlog is not None:
                    self.write_to_tlog(conn_index, m)

        if not packet_received:
            time.sleep(0.01)

    def open_tlog(self):
        self.tlog = open(self.tlog_filepath, mode="wb")

    def init(self):
        if self.tlog_filepath is not None:
            self.open_tlog()
        self.create_connections()
        self.create_connection_maintenance_thread()
        
    def loop(self):
        self.handle_messages()

    def create_connection_maintenance_thread(self):
        '''create and start helper threads and the like'''
        def connection_maintenance_target():
            while self.connection_maintenance_target_should_live:
                self.maintain_connections()
                time.sleep(0.1)
        connection_maintenance_thread = threading.Thread(target=connection_maintenance_target)
        connection_maintenance_thread.start()

    def run(self):
        self.init()

#        print("Entering main loop")
        while True:
            self.loop()

if __name__ == '__main__':

    import argparse
    parser = argparse.ArgumentParser(description="link multiple mavlink connections.")
    parser.add_argument(
        '--tlog',
        type=str,
        help='filepath to write tlog to',
    )
    parser.add_argument("link", nargs="+")

    args = parser.parse_args()

    hub = MAVLinkHub(args.link, tlog=args.tlog)
    hub.run()
