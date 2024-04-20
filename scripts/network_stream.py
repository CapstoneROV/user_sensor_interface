#!/usr/bin/env python
# Node to read network videostream (UDP / RTSP) and publish in ROS using GStreamer
# 
# GStreamer + subprocess:
# https://stackoverflow.com/a/71911592
# https://stackoverflow.com/questions/29794053/streaming-mp4-video-file-on-gstreamer
# https://stackoverflow.com/a/10012262
# https://stackoverflow.com/a/41401487
# https://stackoverflow.com/a/12272262
# 
# ROS:
# http://wiki.ros.org/ROS/Tutorials/WritingPublisherSubscriber%28python%29
# http://wiki.ros.org/cv_bridge/Tutorials/ConvertingBetweenROSImagesAndOpenCVImagesPython

import rospy
import numpy as np
import subprocess as sp
import shlex
import select
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
import signal
def default_sigpipe():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

class NetworkStream:
    def __init__(self):
        # ROS initialization
        self.bridge = CvBridge()
        self.mode = rospy.get_param("~mode")
        self.pub_topic = rospy.get_param("~pub_topic")
        self.width = rospy.get_param("~width")
        self.height = rospy.get_param("~height")
        self.channels = rospy.get_param("~channels")
        self.host = rospy.get_param("~host")
        self.uri_postfix = rospy.get_param("~uri_postfix")
        self.case = rospy.get_param("~exceptional_case", 0)
        self.pub = rospy.Publisher(self.pub_topic, Image, queue_size=5)

    def connect(self):
        # UDP
        if self.mode == 0:
            self.uri = 'udp://' + self.host + self.uri_postfix
            self.sp = sp.Popen(shlex.split(
                'gst-launch-1.0 --quiet udpsrc uri={} close-socket=false multicast-iface=false auto-multicast=true ! application/x-rtp, payload=96 ! queue2 ! rtph264depay ! avdec_h264 ! videoconvert ! capsfilter caps="video/x-raw, format=BGR" ! fdsink'.format(self.uri)
            ), stdout=sp.PIPE)

        # RTSP
        else:
            self.uri = 'rtsp://' + self.host + self.uri_postfix
            self.sp = sp.Popen(shlex.split(
                'gst-launch-1.0 --quiet rtspsrc location={} ! queue2 ! rtph264depay ! avdec_h264 ! videoconvert ! capsfilter caps="video/x-raw, format=BGR" ! fdsink'.format(self.uri)
            ), stdout=sp.PIPE)

    def run(self):
        if self.case:
            try:
                self.handle_case(pre=True)
            except Exception as e:
                rospy.logerr("[network_stream] Exception: {}".format(e))
                return

        self.connect()
        rospy.logwarn("[network_stream] Connected to {}".format(self.uri))
        timeout_countdown = 0
        try:
            while not rospy.is_shutdown():
                # Read with timeout
                p = select.select([self.sp.stdout], [], [], 3)
                if p[0]:
                    # Reset countdown
                    timeout_countdown = 0

                    # Get image from GStreamer
                    raw = self.sp.stdout.read(self.width * self.height * self.channels)
                    read_time = rospy.Time.now()
                    if len(raw) < self.width * self.height * self.channels:
                        break

                    # Process image & publish
                    image = np.frombuffer(raw, np.uint8).reshape((self.height, self.width, self.channels))
                    try:
                        msg = self.bridge.cv2_to_imgmsg(image, "bgr8")
                        msg.header.stamp = read_time
                        self.pub.publish(msg)
                    except CvBridgeError as e:
                        rospy.logwarn("[network_stream] cv_bridge exception: {}".format(e))
                
                else:
                    timeout_countdown += 1
                    rospy.logwarn("[network_stream] GStreamer timed out: {} / 5".format(timeout_countdown))
                    if timeout_countdown == 5:
                        break

        # Catch ROS shutdown exception
        except KeyboardInterrupt:
            pass
        except select.error:
            pass
        except Exception as e:
            rospy.logerr("[network_stream] Exception: {}".format(e))
            
        # Cleanup
        if self.case:
            self.handle_case(post=True)
        self.sp.stdout.close()
        self.sp.kill()

    def handle_case(self, pre=False, post=False):
        # MBE
        if self.case == 1:
            import requests
            api_url = 'http://' + self.host + ':8000/api/v1'
            if pre:
                # Enable the sonar and set the range to 40m
                requests.patch(api_url + '/transponder', json={
                    "enable": True,
                    "sonar_range": 40,
                })
                # Set the data stream type to RTSP. The different possible
                # values are documented in the API docs available on
                # http://192.168.2.42:8000/docs
                response = requests.put(api_url + '/streamtype', json={
                    "value": 2,
                })
                rospy.logwarn("[network_stream] MBE enabled")
            if post:
                # Disable the sonar
                requests.patch(api_url + '/transponder', json={
                    "enable": False,
                })
                rospy.logwarn("[network_stream] MBE disabled")


if __name__ == '__main__':
    rospy.init_node('network_stream', anonymous=True)
    nv = NetworkStream()
    nv.run()
