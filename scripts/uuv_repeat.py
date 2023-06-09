#!/usr/bin/env python3
# Copyright 2023 iamnambiar
# All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import rospy
from geometry_msgs.msg import Pose, Point, Quaternion, Twist
from uuv_teach_repeat.msg import TrackPoint, TrackLog
from std_msgs.msg import Bool
import yaml
import os
from uuv_control_msgs.srv import InitWaypointSet, InitWaypointSetRequest
from uuv_control_msgs.msg import Waypoint
from detection_msgs.msg import BoundingBoxes, BoundingBox

class Repeat(object):
    def __init__(self):
        self._tracklog = TrackLog()
        self._isTrajectoryRunning = False
        trajTrackingTopic = rospy.get_param('~trajectory_tracking_topic', '/trajectory_tracking_on')
        objDetectOutputTopic = rospy.get_param('~bounding_boxes_topic', '/yolov5/detections')
        trajRunningSub = rospy.Subscriber(trajTrackingTopic, Bool, callback=self.checkTrajectoryRunningCallback)
        boundingBoxesSub = rospy.Subscriber(objDetectOutputTopic, BoundingBoxes, self.bounding_boxes_callback)
    
    def checkTrajectoryRunningCallback(self, msg):
        if msg is not None:
            self._isTrajectoryRunning = msg.data
    
    def bounding_boxes_callback(self, bb):
        if bb is not None:
            self._boundingBoxes = bb

    def read_tracklog_from_file(self, filePath):
        if not os.path.isfile(filePath):
            print('Invalid waypoint filename, filename={}'.format(filePath))
            return False
        try:
            self._trackLog = TrackLog()
            with open(filePath, 'r') as wp_file:
                tlsCollection = yaml.safe_load(wp_file)
                self._trackLog.header.frame_id = tlsCollection['header_frame']
                self._trackLog.header.stamp = rospy.Time.now()
                tps = tlsCollection['tracklog']
                for tp_data in tps:
                    position = tp_data['pose'][0]['position']
                    orientation = tp_data['pose'][1]['orientation']
                    tp = TrackPoint()
                    tp.pose = Pose()
                    tp.pose.position = Point(x=position[0], y=position[1], z=position[2])
                    tp.pose.orientation = Quaternion(x=orientation[0], y=orientation[1], z=orientation[2], w=orientation[3])
                    tp.isRecorded = tp_data['isRecorded']
                    tp.boundingBoxes = BoundingBoxes()
                    for bb_data in tp_data['boundingBoxes']:
                        boundingBox = BoundingBox()
                        boundingBox.Class = bb_data['Class']
                        boundingBox.probability = bb_data['probability']
                        boundingBox.xmax = bb_data['xmax']
                        boundingBox.xmin = bb_data['xmin']
                        boundingBox.ymax = bb_data['ymax']
                        boundingBox.ymin = bb_data['ymin']
                        tp.boundingBoxes.bounding_boxes.append(boundingBox)
                    self._trackLog.trackpoints.append(tp)
            return True
        except Exception as e:
            rospy.logerr("Error occured while reading recorded poses from file, message = {}".format(e))
            return False
    
    def repeat_points(self):
        service_name = rospy.get_param('~send_wp_service', '/start_waypoint_list')
        rospy.wait_for_service(service_name)
        try:
            client = rospy.ServiceProxy(service_name, InitWaypointSet)
            rate = rospy.Rate(5)
            req = InitWaypointSetRequest()
            req.start_now = True
            req.max_forward_speed = 0.25
            req.heading_offset = 0.25
            req.interpolator.data = rospy.get_param('~interpolator', 'dubins')
            for tp in self._trackLog.trackpoints:
                waypoint = Waypoint()
                waypoint.header = self._trackLog.header
                waypoint.heading_offset = req.heading_offset
                waypoint.max_forward_speed = req.max_forward_speed
                waypoint.use_fixed_heading = False
                waypoint.point = Point(x=tp.pose.position.x, y=tp.pose.position.y, z=tp.pose.position.z)
                req.waypoints.append(waypoint)

                if tp.isRecorded:
                    res = client(req)
                    if res.success:
                        rospy.sleep(2.)
                        while self._isTrajectoryRunning:
                            rate.sleep()
                        
                        try:
                            if self._boundingBoxes is not None:
                                if tp.boundingBoxes is not None:
                                    self.check_for_bounding_boxes(tp.boundingBoxes)
                        except Exception as e:
                            rospy.logerr(e)

                    else:
                        rospy.logerr('Unable to load trajectory')
                        return False
                    req.waypoints.clear()
        except rospy.ServiceException as e:
            rospy.logerr("{0} service call failed because \"{1}\"".format(service_name, e))
    
    def check_for_bounding_boxes(self, reference_bbs):
        twistTopic = rospy.get_param('~twist_topic', '/cmd_vel')
        twistPub = rospy.Publisher(twistTopic, Twist, queue_size=1)
        referenceClassList = list()
        receivedClassList = list()
        for bb in reference_bbs.bounding_boxes:
            referenceClassList.append(bb.Class)
        startTime = rospy.Time.now()
        duration = rospy.Duration.from_sec(30.0)
        while not rospy.is_shutdown():
            for bb in self._boundingBoxes.bounding_boxes:
                receivedClassList.append(bb.Class)
            
            refTime = rospy.Time.now()
            if set(referenceClassList).issubset(set(receivedClassList)):
                rospy.loginfo("Point inspected")
                break
            else:
                twistMsg = Twist()
                twistMsg.angular.z = 0.5
                rate = rospy.Rate(50)
                while rospy.Time.now() - refTime <= rospy.Duration.from_sec(1.0):
                    twistPub.publish(twistMsg)
                    rate.sleep()
                twistPub.publish(Twist())
            elapsedTime = rospy.Time.now() - startTime
            if elapsedTime >= duration:
                rospy.loginfo('Unable to inspect because not all objects are present')
                break

# if __name__ == "__main__":
#     rospy.init_node('nodee')
#     r = Repeat()
#     r.read_tracklog_from_file('/home/iamnambiar/uuv_ws/src/uuv_teach_repeat/config/tracklog.yaml')
