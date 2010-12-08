########################################################################
# $HeadURL$
# File :    AgentModule.py
# Author :  Adria Casajus
########################################################################
"""
  Base class for all agent modules
"""
__RCSID__ = "$Id$"

import os
import threading
import types
import time
import DIRAC
from DIRAC import S_OK, S_ERROR, gConfig, gLogger, gMonitor, rootPath
from DIRAC.ConfigurationSystem.Client import PathFinder
from DIRAC.FrameworkSystem.Client.MonitoringClient import MonitoringClient
from DIRAC.Core.Utilities.Shifter import setupShifterProxyInEnv
from DIRAC.Core.Utilities import Time

class AgentModule:
  """ Base class for all agent modules
  
      This class is used by the AgentReactor Class to steer the execution of 
      DIRAC Agents.
      
      For this purpose the following methods are used:
      - am_initialize()      just after instantiated
      - am_getPollingTime()  to set the execution frequency
      - am_getMaxCycles()    to determine the number of cycles
      - am_go()              for the actual execution of one cycle
      
      Before each iteration, the following methods are used to determine 
      if the new cycle is to be started.
      - am_getModuleParam( 'alive' )
      - am_checkStopAgentFile()
      - am_removeStopAgentFile()

      To start new execution cycle the following methods are used
      - am_getCyclesDone() 
      - am_setOption( 'MaxCycles', maxCycles ) 
      
      At the same time it provides all Agents with common interface.
      All Agent class must inherit from this base class and must implement
      at least the following method:
      - execute()            main method called in the agent cycle

      Additionally they may provide:
      - initialize()         for initial settings
      - finalize()           the graceful exit

      - beginExecution()     before each execution cycle
      - endExecution()       at the end of each execution cycle
        
      The agent can be stopped either by a signal or by creating a 'stop_agent' file
      in the controlDirectory defined in the agent configuration
  
  """

  def __init__( self, agentName, baseAgentName = False, properties = {} ):
    """
      Common __init__ method for all Agents.
      All Agent modules must define:
      __doc__
      __RCSID__
      They are used to populate __codeProperties
      
      The following Options are used from the Configuration:
      - /LocalSite/InstancePath
      - /DIRAC/Setup
      - Status
      - Enabled
      - PollingTime            default = 120
      - MaxCycles              default = 500
      - ControlDirectory       control/SystemName/AgentName
      - WorkDirectory          work/SystemName/AgentName
      - shifterProxy           '' 
      - shifterProxyLocation   WorkDirectory/SystemName/AgentName/.shifterCred
      
      It defines the following default Options that can be set via Configuration (above):
      - MonitoringEnabled     True
      - Enabled               True if Status == Active
      - PollingTime           120
      - MaxCycles             500
      - ControlDirectory      control/SystemName/AgentName
      - WorkDirectory         work/SystemName/AgentName
      - shifterProxy          False
      - shifterProxyLocation  work/SystemName/AgentName/.shifterCred

      different defaults can be set in the initialize() method of the Agent using am_setOption()
      
      In order to get a shifter proxy in the environment during the execute()
      the configuration Option 'shifterProxy' must be set, a default may be given
      in the initialize() method.

    """
    if baseAgentName and agentName == baseAgentName:
      self.log = gLogger
      standaloneModule = True
    else:
      self.log = gLogger.getSubLogger( agentName, child = False )
      standaloneModule = False

    self.__basePath = gConfig.getValue( '/LocalSite/InstancePath', rootPath )
    self.__getCodeInfo()

    self.__moduleProperties = { 'fullName' : agentName,
                                'section' : PathFinder.getAgentSection( agentName ),
                                'standalone' : standaloneModule,
                                'cyclesDone' : 0,
                                'totalElapsedTime' : 0,
                                'setup' : gConfig.getValue( "/DIRAC/Setup", "Unknown" ) }
    self.__moduleProperties[ 'system' ], self.__moduleProperties[ 'agentName' ] = agentName.split( "/" )
    self.__configDefaults = {}
    self.__configDefaults[ 'MonitoringEnabled'] = True
    self.__configDefaults[ 'Enabled'] = self.am_getOption( "Status", "Active" ).lower() in ( 'active' )
    self.__configDefaults[ 'PollingTime'] = self.am_getOption( "PollingTime", 120 )
    self.__configDefaults[ 'MaxCycles'] = self.am_getOption( "MaxCycles", 500 )
    self.__configDefaults[ 'ControlDirectory' ] = os.path.join( self.__basePath,
                                                                'control',
                                                                *agentName.split( "/" ) )
    self.__configDefaults[ 'WorkDirectory' ] = os.path.join( self.__basePath,
                                                             'work',
                                                             *agentName.split( "/" ) )
    self.__configDefaults[ 'shifterProxy' ] = ''
    self.__configDefaults[ 'shifterProxyLocation' ] = os.path.join( self.__configDefaults[ 'WorkDirectory' ],
                                                                        '.shifterCred' )


    for key in properties:
      self.__moduleProperties[ key ] = properties[ key ]
    self.__moduleProperties[ 'executors' ] = [ ( self.execute, () ) ]
    self.__moduleProperties[ 'alive' ] = True
    self.__moduleProperties[ 'shifterProxy' ] = False

    self.__initializeMonitor()
    self.__initialized = False

  def __getCodeInfo( self ):
    versionVar = "__RCSID__"
    docVar = "__doc__"
    try:
      self.__agentModule = __import__( self.__class__.__module__,
                                       globals(),
                                       locals(),
                                       versionVar )
    except Exception, e:
      self.log.exception( "Cannot load agent module" )
    self.__codeProperties = {}
    for prop in ( ( versionVar, "version" ), ( docVar, "description" ) ):
      try:
        self.__codeProperties[ prop[1] ] = getattr( self.__agentModule, prop[0] )
      except Exception, e:
        self.log.error( "Missing %s" % prop[0] )
        self.__codeProperties[ prop[1] ] = 'unset'
    self.__codeProperties[ 'DIRACVersion' ] = DIRAC.version
    self.__codeProperties[ 'platform' ] = DIRAC.platform

  def am_initialize( self, *initArgs ):
    agentName = self.am_getModuleParam( 'fullName' )
    result = self.initialize( *initArgs )
    if result == None:
      return S_ERROR( "Error while initializing %s module: initialize must return S_OK/S_ERROR" % agentName )
    if not result[ 'OK' ]:
      return S_ERROR( "Error while initializing %s: %s" % ( agentName, result[ 'Message' ] ) )
    self.__checkDir( self.am_getControlDirectory() )
    self.__checkDir( self.am_getWorkDirectory() )

    self.__moduleProperties[ 'shifterProxy' ] = self.am_getOption( 'shifterProxy' )
    if self.am_monitoringEnabled():
      self.monitor.enable()
    if len( self.__moduleProperties[ 'executors' ] ) < 1:
      return S_ERROR( "At least one executor method has to be defined" )
    if not self.am_Enabled():
      return S_ERROR( "Agent is disabled via the configuration" )
    self.log.info( "="*40 )
    self.log.info( "Loaded agent module %s" % self.__moduleProperties[ 'fullName' ] )
    self.log.info( " Site: %s" % DIRAC.siteName() )
    self.log.info( " Setup: %s" % gConfig.getValue( "/DIRAC/Setup" ) )
    self.log.info( " Base Module version: %s " % __RCSID__ )
    self.log.info( " Agent version: %s" % self.__codeProperties[ 'version' ] )
    self.log.info( " DIRAC version: %s" % DIRAC.version )
    self.log.info( " DIRAC platform: %s" % DIRAC.platform )
    pollingTime = self.am_getOption( 'PollingTime' )
    if pollingTime > 3600:
      self.log.info( " Polling time: %s hours" % int(pollingTime) / 3600. )
    else:
      self.log.info( " Polling time: %s seconds" % self.am_getOption( 'PollingTime' ) )
    self.log.info( " Control dir: %s" % self.am_getControlDirectory() )
    self.log.info( " Work dir: %s" % self.am_getWorkDirectory() )
    if self.am_getOption( 'MaxCycles' ) > 0:
      self.log.info( " Cycles: %s" % self.am_getMaxCycles() )
    else:
      self.log.info( " Cycles: unlimited" )
    self.log.info( "="*40 )
    self.__initialized = True
    return S_OK()

  def __checkDir( self, path ):
    try:
      os.makedirs( path )
    except:
      pass
    if not os.path.isdir( path ):
      raise Exception( 'Can not create %s' % path )

  def am_getControlDirectory( self ):
    return os.path.join( self.__basePath, str( self.am_getOption( 'ControlDirectory' ) ) )

  def am_getStopAgentFile( self ):
    return os.path.join( self.am_getControlDirectory(), 'stop_agent' )

  def am_checkStopAgentFile( self ):
    return os.path.isfile( self.am_getStopAgentFile() )

  def am_createStopAgentFile( self ):
    try:
      fd = open( self.am_getStopAgentFile(), 'w' )
      fd.write( 'Dirac site agent Stopped at %s' % Time.toString() )
      fd.close()
    except:
      pass

  def am_removeStopAgentFile( self ):
    try:
      os.unlink( self.am_getStopAgentFile() )
    except:
      pass

  def am_getBasePath( self ):
    return self.__basePath

  def am_getWorkDirectory( self ):
    return os.path.join( self.__basePath, str( self.am_getOption( 'WorkDirectory' ) ) )

  def am_getShifterProxyLocaltion( self ):
    return os.path.join( self.__basePath, str( self.am_getOption( 'shifterProxyLocation' ) ) )

  def am_getOption( self, optionName, defaultValue = None ):
    if defaultValue == None:
      if optionName in self.__configDefaults:
        defaultValue = self.__configDefaults[ optionName ]
    if optionName and optionName[0] == "/":
      return gConfig.getValue( optionName, defaultValue )
    return gConfig.getValue( "%s/%s" % ( self.__moduleProperties[ 'section' ], optionName ), defaultValue )

  def am_setOption( self, optionName, value ):
    self.__configDefaults[ optionName ] = value

  def am_getModuleParam( self, optionName ):
    return self.__moduleProperties[ optionName ]

  def am_setModuleParam( self, optionName, value ):
    self.__moduleProperties[ optionName ] = value

  def am_getPollingTime( self ):
    return self.am_getOption( "PollingTime" )

  def am_getMaxCycles( self ):
    return self.am_getOption( "MaxCycles" )

  def am_getCyclesDone( self ):
    return self.am_getModuleParam( 'cyclesDone' )

  def am_Enabled( self ):
    enabled = self.am_getOption( "Enabled" )
    return self.am_getOption( "Enabled" )

  def am_disableMonitoring( self ):
    self.am_setOption( 'MonitoringEnabled' , False )

  def am_monitoringEnabled( self ):
    return self.am_getOption( "MonitoringEnabled" )

  def am_stopExecution( self ):
    self.am_setModuleParam( 'alive', False )

  def __initializeMonitor( self ):
    """
    Initialize the system monitor client
    """
    if self.__moduleProperties[ 'standalone' ]:
      self.monitor = gMonitor
    else:
      self.monitor = MonitoringClient()
    self.monitor.setComponentType( self.monitor.COMPONENT_AGENT )
    self.monitor.setComponentName( self.__moduleProperties[ 'fullName' ] )
    self.monitor.initialize()
    self.monitor.registerActivity( 'CPU', "CPU Usage", 'Framework', "CPU,%", self.monitor.OP_MEAN, 600 )
    self.monitor.registerActivity( 'MEM', "Memory Usage", 'Framework', 'Memory,MB', self.monitor.OP_MEAN, 600 )
    #Component monitor
    for field in ( 'version', 'DIRACVersion', 'description', 'platform' ):
      self.monitor.setComponentExtraParam( field, self.__codeProperties[ field ] )
    self.monitor.setComponentExtraParam( 'startTime', Time.dateTime() )
    self.monitor.setComponentExtraParam( 'cycles', 0 )
    self.monitor.disable()
    self.__monitorLastStatsUpdate = time.time()

  def am_secureCall( self, functor, args = (), name = False ):
    if not name:
      name = str( functor )
    try:
      result = functor( *args )
      if result == None:
        return S_ERROR( "%s method for %s module has to return S_OK/S_ERROR" % ( name, self.__moduleProperties[ 'fullName' ] ) )
      return result
    except Exception, e:
      self.log.exception( "Exception while calling %s method" % name )
      return S_ERROR( "Exception while calling %s method: %s" % ( name, str( e ) ) )

  def am_go( self ):
    #Set the shifter proxy if required
    if self.__moduleProperties[ 'shifterProxy' ]:
      result = setupShifterProxyInEnv( self.__moduleProperties[ 'shifterProxy' ],
                                       self.am_getShifterProxyLocaltion() )
      if not result[ 'OK' ]:
        self.log.error( result['Message'] )
        return result
    self.log.info( "-"*40 )
    self.log.info( "Starting cycle for module %s" % self.__moduleProperties[ 'fullName' ] )
    mD = self.am_getMaxCycles()
    if mD > 0:
      cD = self.__moduleProperties[ 'cyclesDone' ]
      self.log.info( "Remaining %s of %s cycles" % ( mD - cD, mD ) )
    self.log.info( "-"*40 )
    elapsedTime = time.time()
    cpuStats = self.__startReportToMonitoring()
    cycleResult = self.__executeModuleCycle()
    if cpuStats:
      self.__endReportToMonitoring( *cpuStats )
    #Increment counters
    self.__moduleProperties[ 'cyclesDone' ] += 1
    #Show status
    elapsedTime = time.time() - elapsedTime
    self.__moduleProperties[ 'totalElapsedTime' ] += elapsedTime
    self.log.info( "-"*40 )
    self.log.info( "Agent module %s run summary" % self.__moduleProperties[ 'fullName' ] )
    self.log.info( " Executed %s times previously" % self.__moduleProperties[ 'cyclesDone' ] )
    self.log.info( " Cycle took %.2f seconds" % elapsedTime )
    averageElapsedTime = self.__moduleProperties[ 'totalElapsedTime' ] / self.__moduleProperties[ 'cyclesDone' ]
    self.log.info( " Average execution time: %.2f seconds" % ( averageElapsedTime ) )
    elapsedPollingRate = averageElapsedTime * 100 / self.am_getOption( 'PollingTime' )
    self.log.info( " Polling time: %s seconds" % self.am_getOption( 'PollingTime' ) )
    self.log.info( " Average execution/polling time: %.2f%%" % elapsedPollingRate )
    if cycleResult[ 'OK' ]:
      self.log.info( " Cycle was successful" )
    else:
      self.log.error( " Cycle had an error:", cycleResult[ 'Message' ] )
    self.log.info( "-"*40 )
    #Update number of cycles
    self.monitor.setComponentExtraParam( 'cycles', self.__moduleProperties[ 'cyclesDone' ] )
    return cycleResult

  def __startReportToMonitoring( self ):
    try:
      now = time.time()
      stats = os.times()
      cpuTime = stats[0] + stats[2]
      if now - self.__monitorLastStatsUpdate < 10:
        return ( now, cpuTime )
      # Send CPU consumption mark
      wallClock = now - self.__monitorLastStatsUpdate
      self.__monitorLastStatsUpdate = now
      # Send Memory consumption mark
      membytes = self.__VmB( 'VmRSS:' )
      if membytes:
        mem = membytes / ( 1024. * 1024. )
        gMonitor.addMark( 'MEM', mem )
      return( now, cpuTime )
    except:
      return False

  def __endReportToMonitoring( self, initialWallTime, initialCPUTime ):
    wallTime = time.time() - initialWallTime
    stats = os.times()
    cpuTime = stats[0] + stats[2] - initialCPUTime
    percentage = cpuTime / wallTime * 100.
    if percentage > 0:
      gMonitor.addMark( 'CPU', percentage )

  def __VmB( self, VmKey ):
    '''Private.
    '''
    __memScale = {'kB': 1024.0, 'mB': 1024.0 * 1024.0, 'KB': 1024.0, 'MB': 1024.0 * 1024.0}
    procFile = '/proc/%d/status' % os.getpid()
     # get pseudo file  /proc/<pid>/status
    try:
      t = open( procFile )
      v = t.read()
      t.close()
    except:
      return 0.0  # non-Linux?
     # get VmKey line e.g. 'VmRSS:  9999  kB\n ...'
    i = v.index( VmKey )
    v = v[i:].split( None, 3 )  # whitespace
    if len( v ) < 3:
      return 0.0  # invalid format?
     # convert Vm value to bytes
    return float( v[1] ) * __memScale[v[2]]

  def __executeModuleCycle( self ):
    #Execute the beginExecution function
    result = self.am_secureCall( self.beginExecution, name = "beginExecution" )
    if not result[ 'OK' ]:
      return result
    #Launch executor functions
    executors = self.__moduleProperties[ 'executors' ]
    if len( executors ) == 1:
      result = self.am_secureCall( executors[0][0], executors[0][1] )
      if not result[ 'OK' ]:
        return result
    else:
      exeThreads = [ threading.Thread( target = executor[0], args = executor[1] ) for executor in executors ]
      for thread in exeThreads:
        thread.setDaemon( 1 )
        thread.start()
      for thread in exeThreads:
        thread.join()
    #Execute the endExecution function
    return  self.am_secureCall( self.endExecution, name = "endExecution" )

  def initialize( self, *args, **kwargs ):
    return S_OK()

  def beginExecution( self ):
    return S_OK()

  def endExecution( self ):
    return S_OK()

  def finalize( self ):
    return S_OK()

  def execute( self ):
    return S_ERROR( "Execute method has to be overwritten by agent module" )
