#!/usr/bin/env python
"""Stratux screen updated for modern Python2 (and prepped for Python3).

Notes:
- ImageDraw seems unused, but is supposedly called by canvas.
"""
from __future__ import absolute_import  # remove if imports fail
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import json
import time
import urllib2

from daemon import runner
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306, sh1106
from PIL import Image, ImageDraw, ImageFont


FONT_PATH = '/etc/stratux-screen/CnC_Red_Alert.ttf'
FONT_SIZE = 12  # points

LOGO_PATH = '/etc/stratux-screen/stratux-logo-64x64.bmp'
LOGO_TIME = 5  # seconds; how long to show the logo

# Screen parameters, all in pixels
PADDING = 2  # left and right screen margins
TEXT_MARGIN = 25  # space given to text on either side of status bars
LINE = (  # y-coordinates for lines
    0,  # line 0
    14,
    24,
    34,
    45,
    )
BAR_WIDTH = 6
UAT_INDENT = 50  # Prefer indents to be calculated...
ES_INDENT = 44

DISPLAY_TYPE = 'ssd1306'
#DISPLAY_TYPE = 'sh1106'

I2C_PORT = 1
I2C_ADDRESS = 0x3c
CHECK_PERIOD = 1  # seconds; how long to wait between status checks

PIDFILE_PATH = '/var/run/stratux-screen.pid'
PIDFILE_TIMEOUT = 5  # seconds
STDIN_PATH = '/dev/null'
STDOUT_PATH = '/var/log/stratux-screen.log'
STDERR_PATH = '/var/log/stratux-screen.log'  # perhaps .err


class StratuxScreen(object):
    """Stratux screen class
    """

    def __init__(self):
        """Set up Screen object.
        """
        serial = i2c(port=I2C_PORT, address=I2C_ADDRESS)
        if DISPLAY_TYPE == 'sh1106':
            self.oled = sh1106(serial)
        else:
            self.oled = ssd1306(serial)
        self.bar_length = self.oled.width - ((PADDING + TEXT_MARGIN) * 2)
        self.font = ImageFont.truetype(FONT_PATH, FONT_SIZE)

        # Required by daemon runner
        self.pidfile_path = PIDFILE_PATH
        self.pidfile_timeout = PIDFILE_TIMEOUT
        self.stdin_path = STDIN_PATH
        self.stdout_path = STDOUT_PATH
        self.stderr_path = STDERR_PATH

    def run(self):
        """Called by daemon runner.
        """
        self.splash()
        check_num = 1
        while check_num:
            time.sleep(CHECK_PERIOD)
            status_data = get_status_data()
            mode = check_num <= 5  # switch mode every 5 iterations
            self.display_status_data(status_data, mode)
            check_num += 1
            if check_num > 10:
                check_num = 1  # prevent value overflows by resetting

    def display_status_data(self, status_data, mode):
        """Displays status data on screen.

        Arguments:
            status_data: Status data dictionary.
            mode: Boolean; shows CPU data on True, GPS data on False.
        """
        with canvas(self.oled) as draw:
            # line 0: UAT Heading
            draw.text((UAT_INDENT, LINE[0]), 'UAT', font=self.font, fill=255)
            # line 1: UAT stats
            if status_data['UAT_messages_max']:
                bar_value = self.bar_length * int(
                    (status_data['UAT_messages_last_minute']
                     / status_data['UAT_messages_max']))
            else:
                bar_value = 0
            draw.rectangle((PADDING+TEXT_MARGIN, LINE[1],
                            PADDING+TEXT_MARGIN+bar_value, LINE[1]+BAR_WIDTH),
                           outline=255, fill=255)
            draw.text((PADDING, LINE[1]),
                      str(status_data['UAT_messages_last_minute']),
                      font=self.font, fill=255)
            draw.text(((2*PADDING)+TEXT_MARGIN+self.bar_length, LINE[1]),
                      str(status_data['UAT_messages_max']),
                      font=self.font, fill=255)

            # line 2: ES Heading
            draw.text((ES_INDENT, LINE[2]), '1090ES', font=self.font, fill=255)
            # line 3: ES stats
            if status_data['ES_messages_max']:
                bar_value = self.bar_length * int(
                    (status_data['ES_messages_last_minute']
                     / status_data['ES_messages_max']))
            else:
                bar_value = 0
            draw.rectangle((PADDING+TEXT_MARGIN, LINE[3],
                            PADDING+TEXT_MARGIN+bar_value, LINE[3]+BAR_WIDTH),
                           outline=255, fill=255)
            draw.text((PADDING, LINE[3]),
                      str(status_data['ES_messages_last_minute']),
                      font=self.font, fill=255)
            draw.text(((2*PADDING)+TEXT_MARGIN+self.bar_length, LINE[3]),
                      str(status_data['ES_messages_max']),
                      font=self.font, fill=255)

            # line 4: Other stats
            if mode:
                stat_text = 'CPU: %0.1fC, Towers: %d' % (
                    status_data['CPUTemp'], status_data['num_towers'])
            else:
                stat_text = 'GPS Sat: %d/%d/%d' % (
                    status_data['GPS_satellites_locked'],
                    status_data['GPS_satellites_seen'],
                    status_data['GPS_satellites_tracked'])
                if 'WAAS' in status_data['GPS_solution']:
                    stat_text = '%s (WAAS)' % (stat_text)
            #print(stat_text)
            draw.text((PADDING, LINE[4]), stat_text, font=self.font, fill=255)

    def splash(self):
        """Show centered logo.
        """
        with canvas(self.oled) as draw:
            logo = Image.open(LOGO_PATH)
            x_offset = (self.oled.width - logo.width) // 2
            y_offset = (self.oled.height - logo.height) // 2
            if x_offset < 0:
                x_offset = 0
            if y_offset < 0:
                y_offset = 0
            draw.bitmap((x_offset, y_offset), logo, fill=1)
        time.sleep(LOGO_TIME)


def get_status_data():
    """Get status data (and tower count).

    Returns:
        Parsed JSON data, with added "num_towers" key/value.
    """
    status_data = get_json_response('http://localhost/getStatus')
    towers_data = get_json_response('http://localhost/getTowers')
    num_towers = 0
    for tower_lat_long in towers_data:
        print(towers_data[tower_lat_long]['Messages_last_minute'])
        num_towers += bool(towers_data[tower_lat_long]['Messages_last_minute'])
    status_data['num_towers'] = num_towers
    return status_data


def get_json_response(url):
    """Returns JSON response.

    Arguments:
        url: Request URL.

    Returns:
        Dictionary parsed from JSON response.
    """
    response = urllib2.urlopen(url)
    response_text = response.read()
    response_json = json.loads(response_text)
    return response_json


def main():
    """Daemon caller.
    """
    stratux_screen = StratuxScreen()
    daemon_runner = runner.DaemonRunner(stratux_screen)
    daemon_runner.do_action()


if __name__ == '__main__':
    main()
