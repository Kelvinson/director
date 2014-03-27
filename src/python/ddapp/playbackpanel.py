from PythonQt import QtCore, QtGui, QtUiTools
import ddapp.applogic as app
import math
import numpy as np
from ddapp.timercallback import TimerCallback
from ddapp.simpletimer import SimpleTimer
from ddapp.debugVis import DebugData
import ddapp.visualization as vis
import ddapp.vtkAll as vtk
import scipy.interpolate


def addWidgetsToDict(widgets, d):

    for widget in widgets:
        if widget.objectName:
            d[str(widget.objectName)] = widget
        addWidgetsToDict(widget.children(), d)


class WidgetDict(object):

    def __init__(self, widgets):
        addWidgetsToDict(widgets, self.__dict__)


def clearLayout(w):
    children = w.findChildren(QtGui.QWidget)
    for child in children:
        child.delete()




class PlaybackPanel(object):

    def __init__(self, planPlayback, playbackRobotModel, playbackJointController, robotStateModel, robotStateJointController, manipPlanner):

        self.planPlayback = planPlayback
        self.playbackRobotModel = playbackRobotModel
        self.playbackJointController = playbackJointController
        self.robotStateModel = robotStateModel
        self.robotStateJointController = robotStateJointController
        self.manipPlanner = manipPlanner

        self.visOnly = True
        self.planFramesObj = None
        self.plan = None
        self.poseInterpolator = None
        self.startTime = 0.0
        self.endTime = 1.0
        self.animationTimer = TimerCallback()
        self.animationTimer.targetFps = 60
        self.animationTimer.callback = self.updateAnimation
        self.animationClock = SimpleTimer()

        loader = QtUiTools.QUiLoader()
        uifile = QtCore.QFile(':/ui/ddPlaybackPanel.ui')
        assert uifile.open(uifile.ReadOnly)

        self.widget = loader.load(uifile)
        uifile.close()

        self.ui = WidgetDict(self.widget.children())

        self.ui.viewModeCombo.connect('currentIndexChanged(const QString&)', self.viewModeChanged)
        self.ui.playbackSpeedCombo.connect('currentIndexChanged(const QString&)', self.playbackSpeedChanged)
        self.ui.interpolationCombo.connect('currentIndexChanged(const QString&)', self.interpolationChanged)

        self.ui.samplesSpinBox.connect('valueChanged(int)', self.numberOfSamplesChanged)
        self.ui.playbackSlider.connect('valueChanged(int)', self.playbackSliderValueChanged)

        self.ui.animateButton.connect('clicked()', self.animateClicked)
        self.ui.hideButton.connect('clicked()', self.hideClicked)
        self.ui.executeButton.connect('clicked()', self.executeClicked)
        self.ui.stopButton.connect('clicked()', self.stopClicked)

        self.setPlan(None)
        self.hideClicked()


    def getViewMode(self):
      return str(self.ui.viewModeCombo.currentText)

    def getPlaybackSpeed(self):
      s = str(self.ui.playbackSpeedCombo.currentText).replace('x', '')
      if '/' in s:
          n, d = s.split('/')
          return float(n)/float(d)
      return float(s)

    def getInterpolationMethod(self):
        return str(self.ui.interpolationCombo.currentText)

    def getNumberOfSamples(self):
        return self.ui.samplesSpinBox.value

    def viewModeChanged(self):
        viewMode = self.getViewMode()
        if viewMode == 'continuous':
            playbackVisible = True
            samplesVisible = False
        else:
            playbackVisible = False
            samplesVisible = True

        self.ui.samplesLabel.setEnabled(samplesVisible)
        self.ui.samplesSpinBox.setEnabled(samplesVisible)

        self.ui.playbackSpeedLabel.setVisible(playbackVisible)
        self.ui.playbackSpeedCombo.setVisible(playbackVisible)
        self.ui.playbackSlider.setEnabled(playbackVisible)
        self.ui.animateButton.setVisible(playbackVisible)
        self.ui.timeLabel.setVisible(playbackVisible)

        if self.plan:

            if self.getViewMode() == 'continuous':
                self.startAnimation()
            else:
                self.ui.playbackSlider.value = 0
                self.stopAnimation()
                self.updatePlanFrames()


    def playbackSpeedChanged(self):
        print self.getPlaybackSpeed()
        self.planPlayback.playbackSpeed = self.getPlaybackSpeed()


    def getPlaybackTime(self):
        sliderValue = self.ui.playbackSlider.value
        return (sliderValue / 1000.0) * self.endTime

    def updateTimeLabel(self):
        playbackTime = self.getPlaybackTime()
        self.ui.timeLabel.text = 'Time: %.2f s' % playbackTime

    def playbackSliderValueChanged(self):
        self.updateTimeLabel()
        self.showPoseAtTime(self.getPlaybackTime())

    def interpolationChanged(self):

        methods = {'linear' : 'slinear',
                   'cubic spline' : 'cubic',
                   'pchip' : 'pchip' }
        self.planPlayback.interpolationMethod = methods[self.getInterpolationMethod()]
        self.poseInterpolator = self.planPlayback.getPoseInterpolatorFromPlan(self.plan)
        self.updatePlanFrames()

    def numberOfSamplesChanged(self):
        self.updatePlanFrames()

    def animateClicked(self):
        self.startAnimation()

    def hideClicked(self):

        if self.ui.hideButton.text == 'hide':
            self.ui.playbackFrame.setEnabled(False)
            self.hidePlan()
            self.ui.hideButton.text = 'show'
            self.ui.executeButton.setEnabled(False)

            if not self.plan:
                self.ui.hideButton.setEnabled(False)
        else:
            self.ui.playbackFrame.setEnabled(True)
            self.ui.hideButton.text = 'hide'
            self.ui.hideButton.setEnabled(True)
            self.ui.executeButton.setEnabled(True)

            self.viewModeChanged()


    def executeClicked(self):
        if self.visOnly:
            _, poses = self.planPlayback.getPlanPoses(self.plan)
            self.robotStateJointController.setPose('EST_ROBOT_STATE', poses[-1])
        else:
            self.manipPlanner.commitManipPlan(self.plan)

        self.setPlan(None)
        self.hideClicked()


    def stopClicked(self):
        self.stopAnimation()
        self.manipPlanner.sendPlanPause()


    def updatePlanFrames(self):

        if self.getViewMode() != 'frames':
            return

        numberOfSamples = self.getNumberOfSamples()

        meshes = self.planPlayback.getPlanPoseMeshes(self.plan, self.playbackJointController, self.playbackRobotModel, numberOfSamples)
        d = DebugData()

        startColor = [0.8, 0.8, 0.8]
        endColor = [85/255.0, 255/255.0, 255/255.0]
        colorFunc = scipy.interpolate.interp1d([0, numberOfSamples-1], [startColor, endColor], axis=0, kind='slinear')

        for i, mesh in reversed(list(enumerate(meshes))):
            d.addPolyData(mesh, color=colorFunc(i))

        pd = d.getPolyData()
        clean = vtk.vtkCleanPolyData()
        clean.SetInput(pd)
        clean.Update()
        pd = clean.GetOutput()

        self.planFramesObj = vis.updatePolyData(d.getPolyData(), 'robot plan', alpha=1.0, visible=False, colorByName='RGB255', parent='planning')
        self.showPlanFrames()


    def showPlanFrames(self):
        self.planFramesObj.setProperty('Visible', True)
        self.robotStateModel.setProperty('Visible', False)
        self.playbackRobotModel.setProperty('Visible', False)


    def startAnimation(self):
        self.showPlaybackModel()
        self.stopAnimation()
        self.ui.playbackSlider.value = 0
        self.animationClock.reset()
        self.animationTimer.start()
        self.updateAnimation()


    def stopAnimation(self):
        self.animationTimer.stop()

    def showPlaybackModel(self):
        self.robotStateModel.setProperty('Visible', True)
        self.robotStateModel.setProperty('Alpha', 0.1)
        self.playbackRobotModel.setProperty('Visible', True)
        if self.planFramesObj:
            self.planFramesObj.setProperty('Visible', False)

    def hidePlan(self):
        self.stopAnimation()
        if self.planFramesObj:
            self.planFramesObj.setProperty('Visible', False)
        if self.playbackRobotModel:
            self.playbackRobotModel.setProperty('Visible', False)

        self.robotStateModel.setProperty('Visible', True)
        self.robotStateModel.setProperty('Alpha', 1.0)


    def showPoseAtTime(self, time):
        pose = self.poseInterpolator(time)
        self.playbackJointController.setPose('plan_playback', pose)


    def updateAnimation(self):

        tNow = self.animationClock.elapsed() * self.planPlayback.playbackSpeed
        if tNow > self.endTime:
            tNow = self.endTime

        sliderValue = int(1000.0 * tNow / self.endTime)

        self.ui.playbackSlider.blockSignals(True)
        self.ui.playbackSlider.value = sliderValue
        self.ui.playbackSlider.blockSignals(False)
        self.updateTimeLabel()

        self.showPoseAtTime(tNow)
        return tNow < self.endTime


    def setPlan(self, plan):

        self.ui.playbackSlider.value = 0
        self.ui.timeLabel.text = 'Time: 0.00 s'
        self.ui.planNameLabel.text = ''
        self.plan = plan
        self.endTime = 1.0

        if not self.plan:
            return

        planText = 'Plan: %d.  %.2f seconds' % (plan.utime, self.planPlayback.getPlanElapsedTime(plan))
        self.ui.planNameLabel.text = planText

        self.startTime = 0.0
        self.endTime = self.planPlayback.getPlanElapsedTime(plan)
        self.interpolationChanged()

        if self.ui.hideButton.text == 'show':
            self.hideClicked()
        else:
            self.viewModeChanged()

        self.widget.parent().show()



def init(planPlayback, playbackRobotModel, playbackJointController, robotStateModel, robotStateJointController, manipPlanner):
    global panel
    panel = PlaybackPanel(planPlayback, playbackRobotModel, playbackJointController, robotStateModel, robotStateJointController, manipPlanner)

    #app.getMainWindow().viewManager().layout().addWidget(panel.widget)
    dock = app.addWidgetToDock(panel.widget, dockArea=QtCore.Qt.BottomDockWidgetArea)
    dock.hide()

    return panel