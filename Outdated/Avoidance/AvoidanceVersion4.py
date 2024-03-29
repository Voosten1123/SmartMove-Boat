#Lidar libraries
from rplidar import RPLidar
from array import *
#general
import sys
import random
import math
import argparse
#camera libraries
import cv2
import numpy as np
import depthai
import os
from threading import Thread
import importlib.util
#bridge libraries
import dronekit #dont need all of it so check it out later
from pymavlink import mavutil

#init
lidar = RPLidar('/dev/ttyUSB0')
print ("Connecting")
connection_string = '/dev/ttyACM0'
vehicle = connect(connection_string, wait_ready=True, baud=57600)

#Lidar functions
def get_scan():
    try:
        i = 0 
        for scan in lidar.iter_scans():
            arr = scan            #list of unknown length (scan outputs random number [ 80-120 measurements]). 
            if i == 0:            #[i][j] i = individual measurement, j: 0 quality, 1 angle, 2 distance  
                i +=1             
            else:          #taking the second measurement because the first is almost always erroneous
                break
        lidar.stop()    #clears out lidar buffer, allows function to be called again
        return arr
    except:
        print("fail")

def process_scan(Matrix, RatioVariable, FlagNum, StrengthThres):
    try:
        #produces an array of measurements that are relatively close (ratiovariable/flagnumber control this) along with some derivative variables from said measurements.
        #StregthThres(hold) is used to ensure that we dont return the sea as a wall, suggested value is 14
        #!!!TODO!!! find proper value for strength thres!!!!
        i=0
        flag = 0
        #used to mark and count "close" measurements
        spotslist = []  
        #output array. spotslist[i][j] 
        #i = number of spots. depends on flags
        #j = second array. 4 cells atm. 
        #[i][0] = Mean Quality = Average quality (strength of signal) of the detected measurements (int 0-15, 15 perfect)
        #[i][1] = Mean Angle = the central angle of the detected  measurements (deg)
        #[i][2] = Mean Distance = the distance of the Mean Angle measurement (mm)
        #[i][3] = Length = approximate true length of the measurement. (mm)
        #[i][4] = Shortest Distance = shortest distance of the detected object. (mm)
        #[i][5] = Shortest Distance Angle = Angle of the shortest distance measurement. (deg)
        templ = []
        #temp list to pass variables in output array.

        LMatrix = len(Matrix)
        #-------------------------------------------------------------
        while i<LMatrix-1: #runs for length of input array (get scan doesnt always send the same number of measurements)
            #-------------------------------------------------------------
            rangeA = Matrix[i][2]
            rangeB = Matrix[i+1][2]
            #-------------------------------------------------------------
            if rangeA > rangeB:
                diff = rangeA-rangeB
                if diff == 0:
                    diff = 1
                ratio = diff / rangeA
            #Ratio takes the difference between two consecutive measurements, and it divides the largest distance.
            #Largest distance so the ratio is smaller to get accurate measurements
            #-------------------------------------------------------------
            else:
                diff = rangeB - rangeA
                if diff == 0:
                    diff = 1
                ratio = diff / rangeB
            #same as above
            #-------------------------------------------------------------
            if ratio < RatioVariable and Matrix[i+1][1] - Matrix[i][1] < 5:
                #if the ratio between measurements is within the threshold, they're flagged.
                #AND operator checks so the measurements are in "close" angles, and not just consecutive measurements
                flag += 1
                #templ.append(Matrix[i][1])
            else:
                #if ratio is larger than the threshold, then the two points are not close.
                #the spotted item will be now checked.
                #--------------------------------------
                if flag > FlagNum:
                    #if number of close measurements is above the threshold, then it can be labelled a spot.
                    #--------------------------------------------------
                    #MQ  = Mean Quality
                    j = 0
                    sum = 0
                    while j <= flag:
                        sum = sum + Matrix[i-j][0]
                        j += 1
                    MQ = sum/flag
                    #runs backwards from ending measurement, and finds the average of all the qualities. 
                    #---------------------------------------------------
                    #MD = Mean Distance
                    sum = 0
                    j = 0
                    while j <= flag:
                        sum = sum + Matrix[i-j][2]
                        j += 1
                    MD = sum/flag
                    #same as above, but this time with distance
                    #---------------------------------------------------
                    #MA = Mean Angle
                    MA = Matrix[i - (flag/2)][1]
                    #mean angle is the angle at half the measurements.
                    #--------------------------------------------------
                    #ML = Mean Length
                    deg = 0 #how big the angle is between the ending angle and the starting one
                    deg = Matrix[i][1] - Matrix[i-flag][1]
                    if deg < 0:
                        #if the angles inclue 360/000, then the result will be negative as lets say, 010-352 = -342 degrees.
                        #if that happens, we add 360 to ensure its the correct number
                        deg = deg +360
                    ML = deg * MD * 0.01745 
                    # arc length on a circle circumference is θ * 1/360 * 2 * pi * ρ. 2pi /360 is 0.01745
                    #θ = deg, MD = ρ (approximate)
                    ML = math.sqrt((Matrix[i][2]*Matrix[i][2]) + (Matrix[i-flag][2]*Matrix[i-flag][2]) - 2*(Matrix[i-flag][2]*Matrix[i][2]) * math.cos(deg))
                    #distance between first and last points
                    #simple cosine rule. a^2 = b^2 + c^2 - 2*a*b*Cos(A)
                    #A is opposite angle of face a
                    #a = length wanted, ML
                    #A = deg, angle of the whole item
                    #b = distance of first measurement
                    #c = distance of last measurement
                    #--------------------------------------------------
                    SD = 99999 #shortest distance, typical min search function
                    SDa = 0
                    j = 0
                    while j <+ flag:
                        if Matrix[i-j][2]<SD:
                            SD = Matrix[i-j][2] #passing the new minimum
                            SDa = Matrix[i-j][1] #passing the position of the new minimum
                    #--------------------------------------------------
                    #Wall warning part. 
                    #Largest boat size is 2.5m = 2500mm. largest buoy is 1.4m at largest. 
                    #putting the threshold at 2700 as there's a discrepancy between the measured distance (sensor is not very reliable with distance measurements)
                    #and because the Mean Length function is not totally correct. (measures arc length instead of )
                    templ.append(MQ)
                    templ.append(MA)
                    templ.append(MD)
                    templ.append(ML)
                    templ.append(SD)
                    templ.append(SDa)
                    #adds the variables to templ
                    spotslist.append(templ)
                    #adds the templ tuple to the output array

                templ = [] #empties templ
                flag = 0 #resets flag
            
            i += 1
        
        return spotslist
    except:
        print("fail")

def compare_scans(Scan1, Scan2, QualityThres, AngleThres, DistThres, LengthThres):
    try:
        #takes two (maybe three in Ver3) scans, along with thresholds for: Quality, Angle, Distance, Length.
        #outputs an array of all objects that are within the thresholds (it outputs the latter scan as it was)
        #output to be fed into it as Scan1 with Scan2 being a fresh ProcessScan to update.
        i = 0
        #iterator for Scan1
        Objectslist = []
        #output list, same as scan
        while i < len(Scan1):
            flagQ = False
            flagA = False
            flagD = False
            flagL = False
            #flags for each threshold, capital letter indicating which one. Quality, Angle, Distance, Length
            j = 0
            #Iterator for Scan2
            while j < len(Scan2):
                #embedded loops so each item of Scan1 is checked with each item of Scan2
                if abs(Scan1[i][0] - Scan2[j][0]) < QualityThres:
                    flagQ = True
                if abs(Scan1[i][1] - Scan2[j][1]) < AngleThres:
                    flagA = True
                if abs(Scan1[i][2] - Scan2[j][2]) < DistThres:
                    flagD = True
                if abs(Scan1[i][3] - Scan2[j][3]) < LengthThres:
                    flagL = True
                if flagQ and flagA and flagD and flagL: #not sure if it must be AND for all. could do OR or XOR or smth
                    templ = []
                    #templ.append(Scan1[i])
                    #templ.append(Scan2[j])
                    #Objectslist.append(templ)
                    Objectslist.append(Scan2[j])
                    templ = []
                    #print(Scan2[j][1], Scan2[j][2], ' ', Scan1[i][1], Scan1[i][2])
                    break
                j +=1
            i += 1
        return Objectslist
    except:
        print("fail")

def cleararea():
    try:
        scan1 = process_scan(get_scan, 0.15, 3, 12)
        scan2 = process_scan(get_scan, 0.15, 3, 12)
        scan3 = compare_scans(scan1, scan2, 12, 10, 150, 120)
        if len(scan3) == 0:
            return 999
        else:
            i = 0
            angles = 0
            while i < len(scan3):
                angles = angles + scan3[i][1]
                i+=1
            return angles/i
    except:
        print("fail")

#camera functions and classes 
class Detection:
    def __init__(self, videostream, width, height, floating_model, input_mean, input_std, interpreter, input_details,output_details, boxes_idx, classes_idx, labels, scores_idx, min_conf_threshold, imH, imW, focal_length, vfov, hfov, sensorsize, resH, resW):
        self.obj_array = []
        self.videostream = videostream
        self.width = width
        self.height = height
        self.floating_model = floating_model
        self.input_mean = input_mean
        self.input_std = input_std
        self.interpreter = interpreter
        self.input_details = input_details
        self.output_details = output_details
        self.boxes_idx = boxes_idx
        self.classes_idx = classes_idx
        self.labels = labels
        self.scores_idx = scores_idx
        self.min_conf_threshold = min_conf_threshold
        self.imH = imH
        self.imW = imW
        self.focal_length = focal_length
        self.vfov = vfov
        self.hfov = hfov
        #insert calculation for sensor width and height
        self.sensorw = 4.712
        self.sensorh = 6.2868

        
        self.perform_object_detection()

    def perform_object_detection(self):
        # Grab frame from video stream
        frame1 = self.videostream.read()

        # Acquire frame and resize to expected shape [1xHxWx3]
        frame = frame1.copy()
        #print captured res
        #frame_height, frame_width, _ = frame.shape
        #print("Frame resolution: {}x{}".format(frame_width, frame_height))

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_resized = cv2.resize(frame_rgb, (self.width, self.height))
        input_data = np.expand_dims(frame_resized, axis=0)

        # Normalize pixel values if using a floating model (i.e. if model is non-quantized)
        if self.floating_model:
            input_data = (np.float32(input_data) - self.input_mean) / self.input_std

        # Perform the actual detection by running the model with the image as input
        self.interpreter.set_tensor(self.input_details[0]['index'], input_data)
        self.interpreter.invoke()

        # Retrieve detection results
        boxes = self.interpreter.get_tensor(self.output_details[self.boxes_idx]['index'])[0]  # Bounding box coordinates of detected objects
        classes = self.interpreter.get_tensor(self.output_details[self.classes_idx]['index'])[0]  # Class index of detected objects
        scores = self.interpreter.get_tensor(self.output_details[self.scores_idx]['index'])[0]  # Confidence of detected objects

        # Loop over all detections and draw detection box if confidence is above minimum threshold
        for i in range(len(scores)):
            if ((scores[i] > self.min_conf_threshold) and (scores[i] <= 1.0)):
                # Get bounding box coordinates and draw box
                # Interpreter can return coordinates that are outside of image dimensions, need to force them to be within image using max() and min()
                ymin = int(max(1, (boxes[i][0] * self.imH)))
                xmin = int(max(1, (boxes[i][1] * self.imW)))
                ymax = int(min(self.imH, (boxes[i][2] * self.imH)))
                xmax = int(min(self.imW, (boxes[i][3] * self.imW)))

                cv2.rectangle(frame, (xmin, ymin), (xmax, ymax), (10, 255, 0), 2)

                # Draw label (probably can be deleted)
                object_name = self.labels[int(classes[i])]
                

                if object_name != "none":

                    #Getting all values 
                    obj_x = (xmin+xmax)/2
                    obj_y = (ymin+ymax)/2
                    width_on_sensor = xmax - xmin
                    height_on_sensor = ymax - ymin

                    obj_angle = ((obj_x - 0) / self.imW) * self.hfov - (self.hfov/2)


                    #object size
                    if object_name == "largebuoy":#1.4x1.4x1.2 wxwxh

                        #uncomment if width is prefered over height
                        #size_of_obj = 1400

                        #uncomment if height is prefered over width
                        size_of_obj = 1500
                    elif object_name == "smallbuoy":#57.5d
                        size_of_obj = 575
                    else:
                        size_of_obj = 1000


                    #using height
                    #distance of obj = f(mm) x real height(mm) x image height(pxls) / object height(pxls) x sensor height(mm)
                    obj_z = (self.focal_length * size_of_obj * self.imH)/(height_on_sensor * self.sensorh)

                    #print("{}: Object {}, Distance = {}, Positionx = {}, Positiony = {}".format(i, object_name, obj_z, obj_x, obj_z))

                    self.obj_data = [object_name, obj_z, obj_angle]
                    self.obj_array.append(self.obj_data)

               

    def get_detections(self):
        return self.obj_array

class VideoStream:
    def __init__(self, resolution=(4056, 3040), framerate=5):
        self.pipeline = depthai.Pipeline()
        self.camera = self.pipeline.createColorCamera()
        self.camera.setPreviewSize(resolution[0], resolution[1])
        self.camera.setInterleaved(False)

        self.camera_out = self.pipeline.createXLinkOut()
        self.camera_out.setStreamName("camera")

        self.camera.preview.link(self.camera_out.input)

        self.device = depthai.Device()
        self.device.startPipeline(self.pipeline)

        self.camera_queue = self.device.getOutputQueue("camera", 1, True)

        self.frame = None
        self.stopped = False

    def start(self):
        Thread(target=self.update, args=()).start()
        return self

    def update(self):
        while True:
            if self.stopped:
                return

            in_camera = self.camera_queue.get().getCvFrame()
            self.frame = in_camera.copy()

    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True

#bridge defs // big thanks to Saiffullah Sabir Mohamed from Elucidate drones for most of this < https://www.elucidatedrones.com/posts/how-to-control-drone-with-keyboard-using-dronekit-python/#code-explanation >
def send_to(latitude, longitude, altitude):
    try:
        '''
        This function will send the drone to desired location, when the 
        vehicle is in GUIDED mode.

        Inputs:
            1.  latitude            -   Destination location's Latitude
            2.  longitude           -   Destination location's Longitude
            3.  altitude            -   Vehicle's flight Altitude
        '''

        if vehicle.mode.name == "GUIDED":
            location = LocationGlobalRelative(latitude, longitude, float(altitude))
            vehicle.simple_goto(location)
            time.sleep(1)
    except:
        print("fail")

def destination_location(homeLattitude, homeLongitude, distance, bearing):
    try:
        '''
        This function returns the latitude and longitude of the
        destination location, when distance and bearing is provided.

        Inputs:
            1.  homeLattitude       -   Home or Current Location's  Latitude
            2.  homeLongitude       -   Home or Current Location's  Latitude
            3.  distance            -   Distance from the home location
            4.  bearing             -   Bearing angle from the home location
        '''

        #Radius of earth in metres
        R = 6371e3
        pie = math.pi
        rlat1 = homeLattitude * (pie/180) 
        rlon1 = homeLongitude * (pie/180)

        d = distance

        #Converting bearing to radians
        bearing = bearing * (pie/180)

        rlat2 = math.asin((math.sin(rlat1) * math.cos(d/R)) + (math.cos(rlat1) * math.sin(d/R) * math.cos(bearing)))
        rlon2 = rlon1 + math.atan2((math.sin(bearing) * math.sin(d/R) * math.cos(rlat1)) , (math.cos(d/R) - (math.sin(rlat1) * math.sin(rlat2))))

        #Converting to degrees
        rlat2 = rlat2 * (180/pie) 
        rlon2 = rlon2 * (180/pie)

        # Lat and Long as an Array
        location = [rlat2, rlon2]

        return location
    except:
        print("fail")

def snap_manuever(value):
    try:
        '''
        This function executes short turns 
        Input is a string that is used to define the manuever 
        W - left 90
        NW - left 45
        NNW - left 20
        NNE - right 20
        NE -  right 45
        E - right 90
        '''
        #ship current heading and location
        angle = int(vehicle.heading)
        loc   = (vehicle.location.global_frame.lat, vehicle.location.global_frame.lon, vehicle.location.global_relative_frame.alt)
        
        #distance per step, possibly interuptable. measured in meters
        default_distance = 5
        
        #configure heading 
        if value == 'W':
            NewBearing = angle - 90 
        elif value == 'NW':
            NewBearing = angle - 45 
        elif value == 'NNW':
            NewBearing = angle - 20
        elif value == 'NNE':
            NewBearing = angle + 20
        elif value == 'NE':
            NewBearing = angle + 45 
        elif value == 'E':
            NewBearing = angle + 90     
        
        #execute manuever
        new_loc = destination_location(homeLattitude = loc[0], homeLongitude = loc[1], distance = default_distance, bearing = NewBearing)
        send_to(new_loc[0], new_loc[1], loc[2])
    except:
        print("fail")

def manuever(turn):
    try:
        vehicle.mode="GUIDED"
        #This function executes turns
        #ship current heading and location
        angle = int(vehicle.heading)
        loc   = (vehicle.location.global_frame.lat, vehicle.location.global_frame.lon, vehicle.location.global_relative_frame.alt)
        
        #distance per step, possibly interuptable. measured in meters
        default_distance = 5
        #execute manuever
        NewBearing = angle + turn
        new_loc = destination_location(homeLattitude = loc[0], homeLongitude = loc[1], distance = default_distance, bearing = NewBearing)
        send_to(new_loc[0], new_loc[1], loc[2])
        vehicle.mode="AUTO"
    except:
        print("fail")

def distance_to_current_waypoint():
    try:
        """
        Gets distance in metres to the current waypoint.
        It returns None for the first waypoint (Home location).
        """
        nextwaypoint=vehicle.commands.next
        if nextwaypoint ==0:
            return None
        missionitem=vehicle.commands[nextwaypoint-1] #commands are zero indexed
        lat=missionitem.x
        lon=missionitem.y
        alt=missionitem.z
        targetWaypointLocation=LocationGlobalRelative(lat,lon,alt)
        distancetopoint = get_distance_metres(vehicle.location.global_frame, targetWaypointLocation)
        return distancetopoint
    except:
        print("fail")
#sorting functions

def takeSec(elem):
    try:
        return elem[1]
    except:
        print("fail")
def takeThird(elem):
    try:
        return elem[2]
    except:
        print("fail")
def takeFourth(elem):
    try:
        return elem[3]
    except:
        print("fail")
def takeFifth(elem):
    try:
        return elem[4]
    except:
        print("fail")
def takeSixth(elem):
    try:
        return elem[5]
    except:
        print("fail")
def CurrLat():
    try:
        return vehicle.location.global_frame.lat
    except:
        print("fail")
def CurrLon():
    try:
        return vehicle.location.global_frame.lon
    except:
        print("fail")
def CurrGPS():
    try:
        return vehicle.location.global_frame
    except:
        print("fail")
#TODO
#different races
#avoidance logic
def lidar_check():
    try:
        vehicle.groundspeed = 0.6 #set speed to low so we can get better detections. measured in m/s
        scan1 = process_scan(get_scan(), 0.15, 3, 12)
        scan2 = process_scan(get_scan(), 0.15, 3, 12)
        comp = compare_scans(scan1, scan2, 12, 10, 150, 120)
        #gets a scan for "continuous objects"
        lcomp = len(comp)
        comp.sort(key=takeFourth)
        if lcomp > 0:       #check if we have detected anything
            if lcomp == 1:  #one thing to avoid
                if comp[0][1] < 30 :    #if its ahead of us, right
                    manuever(-30)       #turn left
                elif comp[0][1] > 330:  #if its ahead of us, left
                    manuever(30)        #turn right      
            else:           #multiple things to avoid
                i = 0
                while i < lcomp:
                    if comp[i][4] < 5000:   #if yes, object is in proximity, needs avoidance
                        if comp[i][3] > 2700: #if object detected is longer than 2500m, its a wall
                            if comp[i][5] < 180:    #check for which direction to do a snap manuever
                                snap_manuever("E")
                            else:
                                snap_manuever("W")
                        else:                   #if its below 2500, its not a wall
                            if comp[i][1] < 90:
                                snap_manuever("E")
                            elif comp[i][1] > 270:
                                snap_manuever("W")
                    else:                   #if no, its not in proximity, doesnt need avoidance (unless its a wall)
                        if comp[i][3] > 2700: #if object detected is longer than 2500m, its a wall
                            if comp[i][5] < 180:    #check for which direction to do a snap manuever
                                snap_manuever("NE")
                            else:
                                snap_manuever("NW")
        vehicle.groundspeed = 5     #returning vehicle speed to normal
    except:
        print("fail")

def turning_mode_enable(buoy, angle_thres, distance_thres):
    #checks to see if we're looking at the same buoy, that the distance is correct and that the overall size of the buoy is within limits
    try:
        vehicle.groundspeed = 0.6       #set speed to 0.6m/s, slow enough for the lidar sensor to make measurements
        scan1 = process_scan(get_scan(), 0.2, 3, 12)
        i = 0
        while i < len(scan1):
            if scan1[i][1] - buoy[2] < angle_thres:      #if the detection is close to the buoy
                if scan1[i][2] - buoy[1] < distance_thres: #if the distance is close enough
                    if scan1[i][2] < 10000:
                        vehicle.commands.next = vehicle.commands.next +1
                        #issues command for the vehicle to move to the next waypoint
            i +=1
        if i == len(scan1):
            if scan1[0][2] - buoy[1] <distance_thres*2:
                if scan1[0][1] - buoy[2] <angle_thres*2:
                    vehicle.commands.next = vehicle.commands.next +1
        vehicle.groundspeed = 4        #resume speed to max (max speed is 3.7m/s ish, putting it at 4 so vehicle can go to 100% of approved speeds)
    except:
        print("fail")

def heading_check(buoy):
    try:
        if len(buoy) == 0:
            print("no buoy detected")
        if is_next_waypoint(buoy):
            #alternatively
            manuever(-buoy[0][2])
    except:
        print("fail")

def is_next_waypoint(buoy):
    threshold = 10 #error margin (m)
    buoy_distance = [0][1]/1000
    if distance_to_current_waypoint - buoy_distance < threshold:
        return True
    else:
        return False

def camera_check(detections, distance):
    try:
        if racemode == 1:
            finishline = 0
            ldet = len(detections)
            if ldet>0:      #only check cam if there's a detection
                if ldet == 1:       #if its only 1 detection
                    if detections[0][2] <10 and detections[0][2] >350:  #is it in front of me
                        if detections[0][1] < distance:            #is it within limits?
                            if detections[0][0] == "largebuoy": #its a large buoy
                                vehicle.commands.next = vehicle.commands.next +1     #issues command for the vehicle to switch waypoints
                                speed_race_wp_marker = speed_race_wp_marker + 1 
                            else:                               #its a small buoy
                                print("seeing small buoy")   #this should be a false input, since there's no small buoys at the speed race
                    else:
                        if detections[0][0] == "largebuoy":      #its a large buoy but its not in front of me
                            heading_check(detections)        
                else:               #if its multiple
                    i = 0
                    largebuoyflags = []     #large buoy flag, marks the position of the large buoy in the array given
                    while i < ldet:
                        if detections[i][0] == "largebuoy":
                            largebuoyflags.append(i)
                    if len(largebuoyflags)==2 and speed_race_wp_marker == 3:
                        angle1 = detections[largebuoyflags[0]][3]
                        angle2 = detections[largebuoyflags[0]][2]
                        finishline = (angle1+angle2)/2
                        manuever(finishline)        #aims for inbetween the buoys
        elif racemode == 2:
            ldet = len(detections)
            if ldet>0:      #only check cam if there's a detected
                if ldet == 1:       #if its only 1 detection
                    if detections[0][2] <10 and detections[0][2] >350:  #is it in front of me
                        if detections[0][1] < distance:            #is it a possible threat
                            if detections[0][0] == "largebuoy": #its a large buoy
                                turning_mode_enable(detections[0])
                            else:                               #its a small buoy
                                if detections[0][1] > 3000:     #small buoy is not dangerously close
                                    if detections[0][2] <0:
                                        snap_manuever("NNW")     #  
                                    else:
                                        snap_manuever("NNE")
                                else:                           #small buoy is dangerously close
                                    if detections[0][2] <0:     #if its above 0 degrees, its to the right. so we avoid to the left
                                        snap_manuever("W")
                                    else:                        #if its below 0 deg, its to the left, so we avoid to the right
                                        snap_manuever("E")
                    else:
                        if detections[0][0] == "largebuoy":      #its a large buoy but its not in front of me
                            heading_check(detections)
                            #alternatively
                            #maneuver(detections[0][2])
                            #or
                            '''
                            taget = []
                            target = desination_location(CurrLat, CurrLon, detections[0][1], detections[0][2])
                            send_to(target[0], target[1], 0)
                            '''
                            
                else:               #if its multiple
                    i = 0
                    flagmin = 0
                    largenum = 0
                    smallnum = 0
                    while i < ldet:     #finding the closest
                        if detections[i][1] > detections[flagmin][1]:
                            flagmin = i
                        if detections[i][0] == "largebuoy":
                            largenum += 1
                        else:
                            smallnum += 1
                        i += 1
                    if largenum < 2:
                        if detections[flagmin][1]<distance:     #the closest buoy is in the danger zone
                            manuever(-detections[flagmin][2])
        elif racemode == 3:
            finishline = 0
            ldet = len(detections)
            if ldet>0:      #only check cam if there's a detection
                if ldet == 1:       #if its only 1 detection
                    if detections[0][2] <10 and detections[0][2] >350:  #is it in front of me
                        if detections[0][1] < distance:            #is it within limits?
                            if detections[0][0] == "largebuoy": #its a large buoy
                                vehicle.commands.next = vehicle.commands.next +1     #issues command for the vehicle to switch waypoints
                                speed_race_wp_marker = speed_race_wp_marker + 1 
                            else:                               #its a small buoy
                                print("seeing small buoy")   #this should be a false input, since there's no small buoys at the speed race
                    else:
                        if detections[0][0] == "largebuoy":      #its a large buoy but its not in front of me
                            heading_check(detections)
        elif racemode ==4:
            print("testing")
        else:
            print("unknown racemode")
    except:
        print("fail")

racemode = 0
'''
1 = speed race      #no small buoys other boats possible
2 = avoidance race  #small buoys, other boats guaranteed
3 = endurance race  #no small buoys, other boats guaranteed
4 = testing
'''
end_condition = 0
speed_race_wp_marker = 0
try:
    i = 0
    if racemode == 2 or racemode == 3:
        while True:
            camera_check(Detection.get_detections(),10000)
            if i % 4 == 0:
                lidar_check()
            if i == 20:
                i = 0
            i += 1
    elif racemode == 1:
        while True:
            camera_check(Detection.get_detections(), 10000)
            if end_condition == 1:
                break
    elif racemode == 4:
        print("choose what to test")
        print("1 = lidar | 2 = camera | 3 = heading check")
        x = input()
        if x == 1:
            lidar_check()
        elif x == 2:
            camera_check()
        elif x == 3:
            heading_check()
        else:
            print("unknown command")
except:
    print("fail")