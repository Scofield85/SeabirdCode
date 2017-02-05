"""
Thermocline Class
"""
import numpy as np
import traceback
import sys
from models.model_HMM import hmmModel
from models.model_segmentation import bottomUp
from models.model_threshold import thresholdModel
from tools.signalProcessing import extractSignalFeatures

class thermocline_base(object):
	"""
	Base class for thermocline.
	"""
	def __init__(self,config):
		"""
		Args:
			config: configuration dictionary
		"""
		self.LEP = None
		self.TRM = None
		self.UHY = None
		self.config = config
		
	def detect(self,data):
		'''
		data is a data frame with Depth and Temperature
		'''
		raise ValueError("not implementated")

class thermocline_segmentation(thermocline_base):
	"""
	Class to detect TRM using time series segmentation methods
	"""
	def __init__(self,config):
		"""
		Args:
			config: configuration dictionary
		"""
		super(thermocline_segmentation, self).__init__(config)
		self.TRM_gradient = None
		self.num_segments = None
		self.num_belowTRM = None
		self.model = None
		self.depthInterval = self.config["Preprocessing"]["Interval"]
		self.positiveSeg = []
		self.doubleTRM = []
		self.gradient = []

	def getGradientFromSegment(self,seg):
		"""
		Function to get gradients of each segment, 
		positive means the temperature is decreasing with depth

		Args:
			seg: a list [fitted line, point index]
		Returns:
			the gradient of seg
		"""
		return (seg[0][0]-seg[0][1])/self.depthInterval

	def detectDoubleTRM(self,segmentList):
		"""
		Functions to detect double thermocline. The index of segments which represent
		double thermocline will be appended to doubleTRM

		Args:
			segmentList: a list stores all the segments
		Retures:
			None
		"""
		for i in range(1,len(segmentList)-1):
			segGradient = self.getGradientFromSegment(segmentList[i])
			previousSegGradient = self.getGradientFromSegment(segmentList[i-1])
			nextSegGradient = self.getGradientFromSegment(segmentList[i+1])

			if abs(segGradient) < self.config["Algorithm"]["segment"]["stable_gradient"] and \
				previousSegGradient > self.config["Algorithm"]["segment"]["minTRM_gradient"] and \
				nextSegGradient > self.config["Algorithm"]["segment"]["stable_gradient"]:

				self.doubleTRM.append(i)

		if len(self.doubleTRM)>0:
			print "detected double thermocline", self.doubleTRM

	def detectPositiveGradient(self,segmentList):
		"""
		Functions to detect positive gradient, since positive gradient is abnormal. 
		The index of such segments will be appended to positiveSeg

		Args:
			segmentList: a list stores all the segments
		Retures:
			None
		"""

		self.positiveSeg = []
		for i, seg in enumerate(segmentList):
			gradient = self.getGradientFromSegment(seg)
			if gradient < -1*self.config["Algorithm"]["segment"]["stable_gradient"]:
				self.positiveSeg.append(i)

	def detect(self,data,saveModel = False):
		"""
		Function to detect the thermocline
		Args:
			data: a pandas dataframe
			saveModel: whether to save detection model
		Returns:
			None
		"""
		model = bottomUp(max_error = self.config["Algorithm"]["segment"]["max_error"])
		
		# detect the TRM features
		model.fit_predict(data.Temperature)

		segmentList = model.segmentList # segmentList is a list of [fitted line, point index]

		depthInterval = data.Depth[1]-data.Depth[0]
		
		# get the gradient of all segments
		gradient = [self.getGradientFromSegment(seg) for seg in model.segmentList]
		
		stableGradient = self.config["Algorithm"]["segment"]["stable_gradient"]
		stableGradient2 = self.config["Algorithm"]["segment"]["stable_gradient2"]

		maxGradient_index = np.argmax(gradient)
		
		# remove the segment caused by the noise
		if maxGradient_index == 0:
			tmpDepth = np.array(data.Depth[segmentList[maxGradient_index][1]])
			if tmpDepth[-1] - tmpDepth[0] < 2:
				# if the first segment is less than 2 meters and has the maximum gradient
				# then the first segment would be a noise or peak, need to remove
				print "**** first segment is affected by noise",tmpDepth
				model.segmentList.pop(0)
				gradient = [self.getGradientFromSegment(seg) for seg in model.segmentList]
				maxGradient_index = np.argmax(gradient)

		self.gradient = gradient
		print "Gradient",gradient

		if gradient[maxGradient_index] >self.config["Algorithm"]["segment"]["minTRM_gradient"]: 
			# TRM gradient is above the maximum gradient

			# Detect TRM, which is the middle point of the segment with maximum gradient
			self.TRM = data.Depth[int(np.mean(segmentList[maxGradient_index][1]))]

			# Detect LEP
			epilimnion_seg = model.segmentList[0]
			LEP_index = epilimnion_seg[1][-1] # the end point of the segment.
			
			if maxGradient_index == 0: 
				# if maximum gradient is the first segment, no LEP is detected
				LEP_index = None

			elif abs(gradient[1]) < stableGradient: 
			# if the first seg is anomaly and second seg is stable
					LEP_index = model.segmentList[1][1][-1]
			elif abs(gradient[0]) > stableGradient2:
					LEP_index = None

			# Detect the HYP
			hypolimnion_seg = model.segmentList[-1]
			UHY_index = hypolimnion_seg[1][0]

			if maxGradient_index == len(gradient)-1: # if the TRM is the last segment
				UHY_index = None # No UHY in this profile

			elif abs(gradient[-2])< stableGradient: 
				# if the last second one is stable
				UHY_index = model.segmentList[-2][1][0] # pick the second to the last as the HYP
			
			elif abs(gradient[-1]) > stableGradient2: 
				# if last one still has large gradient
				print "NO UHY",abs(gradient[-1])
				UHY_index=None # No UHY in this profile

			if LEP_index is not None:
				self.LEP = data.Depth[LEP_index]

			if UHY_index is not None:
				self.UHY = data.Depth[UHY_index]
		else:
			print "minimum Gradient",gradient[maxGradient_index],self.config["Algorithm"]["segment"]["minTRM_gradient"]
			print "No TRM deteted"
		
		self.TRM_gradient = max(gradient)
		self.num_segments = len(segmentList)
		self.TRM_idx = maxGradient_index
		
		self.detectDoubleTRM(segmentList)
		self.detectPositiveGradient(segmentList)

		if saveModel:
			self.model = model

class thermocline_HMM(thermocline_base):
	"""
	HMM model
	"""
	def detect(self,data):
		signal_data = extractSignalFeatures(data, "Temperature")
		model = hmmModel(nc = 3)
		res = model.fit_predict(signal_data)
		self.TRM = signal_data.Depth[res[0]]
		self.LEP = signal_data.Depth[res[1]]
		self.UHY = signal_data.Depth[res[2]]

class thermocline_threshold(thermocline_base):
	def detect(self,data):
		signal_data = extractSignalFeatures(data, "Temperature")
		model = thresholdModel(threshold = None)
		res = model.fit_predict(signal_data.Power)
		self.TRM = signal_data.Depth[res[0]]
		self.LEP = signal_data.Depth[res[1]]
		self.UHY = signal_data.Depth[res[2]]

class thermocline(object):
	"""
	Function to detect
	"""
	def __init__(self,config):
		self.config = config
		self.features = {}
		self.models = {}
		
	def detect(self,data,methods = ["segmentation","HMM","threshold"], saveModel = True):
		"""
		Function to detect features of thermocline
		Args:
			data: preprocessed data, a pandas dataframe
			methods: a list indicating which algorithms to use
			saveModel: whether to save model
		Returns:
			features: a dictionary stored the TRM features
		"""
		features = {}
		# initialize Features
		for d in ["TRM","LEP","UHY"]:
			for m in ["segment","HMM","threshold"]:
				features[d+"_"+m] = None
		features["TRM_gradient_segment"] = None
		features["TRM_num_segment"] = None

		# try each model one by one.

		if "segmentation" in methods:
			try:
				model = thermocline_segmentation(self.config)
				model.detect(data,saveModel = saveModel)

				# the gradient of TRM
				features["TRM_gradient_segment"] = model.TRM_gradient

				# the depth of TRM, LEP and UHY
				features["TRM_segment"] = model.TRM
				features["LEP_segment"] = model.LEP
				features["UHY_segment"] = model.UHY
				
				# the number of segments
				features["TRM_num_segment"] = model.num_segments

				# which segment is the TRM
				features["TRM_idx"] = model.TRM_idx

				# how many double TRM sequences
				features["doubleTRM"] = len(model.doubleTRM)

				# how many positive gradient segments
				features["positiveGradient"] = len(model.positiveSeg)

				# the gradient of the some key segments
				features["firstSegmentGradient"] = model.gradient[0]
				features["lastSegmentGradient"] = model.gradient[-1]
				features["lastButTwoSegmentGradient"] = model.gradient[-2]

				if saveModel:
					self.models["segmentation"] = model.model

			except Exception,err:
				print "segmentation Fail"
				print(traceback.format_exc())

		if "HMM" in methods:
			try:
				model = thermocline_HMM(self.config)
				model.detect(data)
				# the depth of TRM, LEP and UHY
				features["TRM_HMM"] = model.TRM
				features["LEP_HMM"] = model.LEP
				features["UHY_HMM"] = model.UHY
			except Exception,err:
				print "HMM Fail"
				print(traceback.format_exc())

		if "threshold" in methods:
			try:
				model = thermocline_threshold(self.config)
				model.detect(data)

				# the depth of TRM, LEP and UHY
				features["TRM_threshold"] = model.TRM
				features["LEP_threshold"] = model.LEP
				features["UHY_threshold"] = model.UHY
			except Exception,err:
				print "threshold Fail"
				print(traceback.format_exc())

		return features


