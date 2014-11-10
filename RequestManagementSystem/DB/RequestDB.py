########################################################################
# $HeadURL $
# File: RequestDB.py
# Author: Krzysztof.Ciba@NOSPAMgmail.com
# Date: 2012/12/04 08:06:30
########################################################################
""" :mod: RequestDB
    =======================

    .. module: RequestDB
    :synopsis: db holding Requests
    .. moduleauthor:: Krzysztof.Ciba@NOSPAMgmail.com

    db holding Request, Operation and File
"""
__RCSID__ = "$Id $"
# #
# @file RequestDB.py
# @author Krzysztof.Ciba@NOSPAMgmail.com
# @date 2012/12/04 08:06:51
# @brief Definition of RequestDB class.

# # imports
import random
import threading
import socket
import MySQLdb.cursors
from MySQLdb import Error as MySQLdbError
from types import StringTypes
import datetime
# # from DIRAC
from DIRAC import S_OK, S_ERROR, gConfig, gLogger
from DIRAC.Core.Base.DB import DB
from DIRAC.Core.Utilities.List import stringListToString
from DIRAC.RequestManagementSystem.Client.Request import Request
from DIRAC.RequestManagementSystem.Client.Operation import Operation
from DIRAC.RequestManagementSystem.Client.File import File
from DIRAC.RequestManagementSystem.private.RMSBase import RMSBase
from DIRAC.ConfigurationSystem.Client.PathFinder import getDatabaseSection

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.orm import relationship, backref, sessionmaker, joinedload_all, mapper
from sqlalchemy import create_engine
from sqlalchemy.sql import update
from sqlalchemy import inspect
from sqlalchemy import func, Table, Column, MetaData
from sqlalchemy import Column, ForeignKey, Integer, String, DateTime, Enum, BLOB, BigInteger





fileTable = Table( 'File', RMSBase.metadata,
            Column( 'FileID', Integer, primary_key = True ),
            Column( 'OperationID', Integer,
                        ForeignKey( 'Operation.OperationID', ondelete = 'CASCADE' ),
                        nullable = False ),
            Column( 'Status', Enum( 'Waiting', 'Done', 'Failed', 'Scheduled' ), server_default = 'Waiting' ),
            Column( 'LFN', String( 255 ), index = True ),
            Column( 'PFN', String( 255 ) ),
            Column( 'ChecksumType', Enum( 'ADLER32', 'MD5', 'SHA1', '' ), server_default = '' ),
            Column( 'Checksum', String( 255 ) ),
            Column( 'GUID', String( 36 ) ),
            Column( 'Size', BigInteger ),
            Column( 'Attempt', Integer ),
            Column( 'Error', String( 255 ) ),
            mysql_engine = 'InnoDB'
        )

mapper( File, fileTable, properties = {
   '_Status': fileTable.c.Status,
   '_LFN': fileTable.c.LFN,
   '_ChecksumType' : fileTable.c.ChecksumType,
   '_GUID' : fileTable.c.GUID,
} )



operationTable = Table( 'Operation', RMSBase.metadata,
                        Column( 'TargetSE', String( 255 ) ),
                        Column( 'CreationTime', DateTime ),
                        Column( 'SourceSE', String( 255 ) ),
                        Column( 'Arguments', BLOB ),
                        Column( 'Error', String( 255 ) ),
                        Column( 'Type', String( 64 ), nullable = False ),
                        Column( 'Order', Integer, nullable = False ),
                        Column( 'Status', Enum( 'Waiting', 'Assigned', 'Queued', 'Done', 'Failed', 'Canceled', 'Scheduled' ), server_default = 'Queued' ),
                        Column( 'LastUpdate', DateTime ),
                        Column( 'SubmitTime', DateTime ),
                        Column( 'Catalog', String( 255 ) ),
                        Column( 'OperationID', Integer, primary_key = True ),
                        Column( 'RequestID', Integer,
                                  ForeignKey( 'Request.RequestID', ondelete = 'CASCADE' ),
                                  nullable = False ),
                       mysql_engine = 'InnoDB'
                       )



mapper(Operation, operationTable, properties={
   '_CreationTime': operationTable.c.CreationTime,
   '_Order': operationTable.c.Order,
   '_Status': operationTable.c.Status,
   '_LastUpdate': operationTable.c.LastUpdate,
   '_SubmitTime': operationTable.c.SubmitTime,
   '_Catalog': operationTable.c.Catalog,
   '__files__':relationship( File,
                            backref = backref( '_parent', lazy = 'immediate' ),
                            lazy = 'immediate',
                            passive_deletes = True,
                            cascade = "all, delete-orphan" )

})


requestTable = Table( 'Request', RMSBase.metadata,
                        Column( 'DIRACSetup', String( 32 ) ),
                        Column( 'CreationTime', DateTime ),
                        Column( 'JobID', Integer, server_default = '0' ),
                        Column( 'OwnerDN', String( 255 ) ),
                        Column( 'RequestName', String( 255 ), nullable = False, unique = True ),
                        Column( 'Error', String( 255 ) ),
                        Column( 'Status', Enum( 'Waiting', 'Assigned', 'Done', 'Failed', 'Canceled', 'Scheduled' ), server_default = 'Waiting' ),
                        Column( 'LastUpdate', DateTime ),
                        Column( 'OwnerGroup', String( 32 ) ),
                        Column( 'SubmitTime', DateTime ),
                        Column( 'RequestID', Integer, primary_key = True ),
                        Column( 'SourceComponent', BLOB ),
                        mysql_engine = 'InnoDB'

                       )



mapper( Request, requestTable, properties = {
   '_CreationTime': requestTable.c.CreationTime,
   '_Status': requestTable.c.Status,
   '_LastUpdate': requestTable.c.LastUpdate,
   '_SubmitTime': requestTable.c.SubmitTime,
   '__operations__' : relationship( Operation,
                                  backref = backref( '_parent', lazy = 'immediate' ),
                                  order_by = operationTable.c.Order,
                                  lazy = 'immediate',
                                  passive_deletes = True,
                                  cascade = "all, delete-orphan"
                                )

} )







########################################################################
class RequestDB( DB ):
  """
  .. class:: RequestDB

  db holding requests
  """
#
#   def __init__( self, systemInstance = 'Default', maxQueueSize = 10 ):
#     """c'tor
#
#     :param self: self reference
#     """
#     self.getIdLock = threading.Lock()
#     DB.__init__( self, "ReqDB", "RequestManagement/ReqDB", maxQueueSize )


  def __getDBConnectionInfo( self, fullname ):
    """ Collect from the CS all the info needed to connect to the DB.
        This should be in a base class eventually
    """
    self.fullname = fullname
    self.cs_path = getDatabaseSection( self.fullname )

    self.dbHost = ''
    result = gConfig.getOption( self.cs_path + '/Host' )
    if not result['OK']:
      raise RuntimeError( 'Failed to get the configuration parameters: Host' )
    self.dbHost = result['Value']
    # Check if the host is the local one and then set it to 'localhost' to use
    # a socket connection
    if self.dbHost != 'localhost':
      localHostName = socket.getfqdn()
      if localHostName == self.dbHost:
        self.dbHost = 'localhost'

    self.dbPort = 3306
    result = gConfig.getOption( self.cs_path + '/Port' )
    if not result['OK']:
      # No individual port number found, try at the common place
      result = gConfig.getOption( '/Systems/Databases/Port' )
      if result['OK']:
        self.dbPort = int( result['Value'] )
    else:
      self.dbPort = int( result['Value'] )

    self.dbUser = ''
    result = gConfig.getOption( self.cs_path + '/User' )
    if not result['OK']:
      # No individual user name found, try at the common place
      result = gConfig.getOption( '/Systems/Databases/User' )
      if not result['OK']:
        raise RuntimeError( 'Failed to get the configuration parameters: User' )
    self.dbUser = result['Value']
    self.dbPass = ''
    result = gConfig.getOption( self.cs_path + '/Password' )
    if not result['OK']:
      # No individual password found, try at the common place
      result = gConfig.getOption( '/Systems/Databases/Password' )
      if not result['OK']:
        raise RuntimeError( 'Failed to get the configuration parameters: Password' )
    self.dbPass = result['Value']
    self.dbName = ''
    result = gConfig.getOption( self.cs_path + '/DBName' )
    if not result['OK']:
      raise RuntimeError( 'Failed to get the configuration parameters: DBName' )
    self.dbName = result['Value']


  def __init__( self, systemInstance = 'Default', maxQueueSize = 10 ):
    """c'tor

    :param self: self reference
    """

    self.log = gLogger.getSubLogger( 'RequestDB' )
    self.__getDBConnectionInfo( 'RequestManagement/ReqDB' )


    # Create an engine that stores data in the local directory's
    # sqlalchemy_example.db file.

    runDebug = ( gLogger.getLevel() == 'DEBUG' )
    self.engine = create_engine( 'mysql://%s:%s@%s/%s' % ( self.dbUser, self.dbPass, self.dbHost, self.dbName ), echo = runDebug )

    # Create all tables in the engine. This is equivalent to "Create Table"
    # statements in raw SQL.
    # Base.metadata.create_all(engine)

    RMSBase.metadata.bind = self.engine

    self.DBSession = sessionmaker( bind = self.engine )


#   def createTables( self, toCreate = None, force = False ):
#     """ create tables """
#     toCreate = toCreate if toCreate else []
#     if not toCreate:
#       return S_OK()
#     tableMeta = self.getTableMeta()
#     metaCreate = {}
#     for tableName in toCreate:
#       metaCreate[tableName] = tableMeta[tableName]
#     if metaCreate:
#       return self._createTables( metaCreate, force )
#     return S_OK()


  def createTables( self, toCreate = None, force = False ):
    """ create tables """
    try:
      RMSBase.metadata.create_all( self.engine )
    except Exception, e:
      return S_ERROR( e )
    return S_OK()

  @staticmethod
  def getTableMeta():
    """ get db schema in a dict format """
    return dict( [ ( classDef.__name__, None )
                   for classDef in ( Request, Operation, File ) ] )

#   def getTables( self ):
#     """ get tables """
#     showTables = self._query( "SHOW TABLES;" )
#     if not showTables["OK"]:
#       return showTables
#     return S_OK( [ table[0] for table in showTables["Value"] if table ] )
#   
  
  def getTables(self):
    return S_OK( RMSBase.metadata.tables.keys() )

#   def dictCursor( self, conn = None ):
#     """ get dict cursor for connection :conn:
#
#     :return: S_OK( { "cursor": MySQLdb.cursors.DictCursor, "connection" : connection  } ) or S_ERROR
#     """
#     if not conn:
#       retDict = self._getConnection()
#       if not retDict["OK"]:
#         self.log.error( retDict["Message"] )
#         return retDict
#       conn = retDict["Value"]
#     cursor = conn.cursor( cursorclass = MySQLdb.cursors.DictCursor )
#     return S_OK( ( conn, cursor ) )
#
#   def _transaction( self, queries ):
#     """ execute transaction """
#     queries = [ queries ] if type( queries ) in StringTypes else queries
#     # # get cursor and connection
#     getCursorAndConnection = self.dictCursor()
#     if not getCursorAndConnection["OK"]:
#       self.log.error( getCursorAndConnection["Message"] )
#       return getCursorAndConnection
#     connection, cursor = getCursorAndConnection["Value"]
#     # # this will be returned as query result
#     ret = { "OK" : True }
#     queryRes = { }
#     # # switch off autocommit
#     connection.autocommit( False )
#     try:
#       # # execute queries
#       for query in queries:
#         print 'QUERY %s' % query
#         cursor.execute( query )
#         queryRes[query] = list( cursor.fetchall() )
#       # # commit
#       connection.commit()
#       # # save last row ID
#       lastrowid = cursor.lastrowid
#       # # close cursor
#       cursor.close()
#       ret["Value"] = queryRes
#       ret["lastrowid"] = lastrowid
#       connection.autocommit( True )
#       return ret
#     except MySQLdbError, error:
#       print 'REQUEST--%s--' % queries
#       self.log.exception( error )
#       # # rollback
#       connection.rollback()
#       # # rever autocommit
#       connection.autocommit( True )
#       # # close cursor
#       cursor.close()
#       return S_ERROR( str( error ) )


#   def cancelRequest( self, request_name ):
#     """ Set the status of a request to Cancel
#         :param request_name : name of the request
# 
#         :returns the request ID
#     """
#     query = "SELECT `RequestID` from `Request` WHERE `RequestName` = '%s'" % request_name
#     ret = self._transaction( query )
#     if not ret["OK"]:
#       self.log.error( "putRequest: %s" % ret["Message"] )
#       return ret
# 
#     reqValues = ret["Value"].get( query )
# 
#     if not reqValues:
#       return S_ERROR( "No such request %s" % request_name )
# 
#     ReqID = reqValues[0].get( "RequestID" )
# 
#     query = "UPDATE Request set Status = 'Canceled', LastUpdate = UTC_TIMESTAMP() where RequestID = %s" % ReqID
#     res = self._transaction( query )
#     if not res["OK"]:
#       self.log.error( "cancelRequest: unable to cancel request %s" % request_name, res["Message"] )
#       return S_ERROR( "cancelRequest: unable to cancel request %s" % request_name )
# 
#     return S_OK( ReqID )


  def cancelRequest(self, request_name):
    session = self.DBSession()
    try:
      updateRet = session.execute( update( Request )\
                         .where( Request.RequestName == request_name )\
                         .values( {Request._Status : 'Canceled',
                                   Request._LastUpdate : datetime.datetime.utcnow()\
                                                        .strftime( RMSBase._datetimeFormat )
                                  }
                                 )
                       )
      session.commit()
      
      # No row was changed
      if not updateRet.rowcount:
        return S_ERROR("No such request %s"%request_name)

      return S_OK()

    except Exception, e:
      session.rollback()
      self.log.exception( "cancelRequest: unexpected exception", lException = e )
      return S_ERROR( "cancelRequest: unexpected exception %s" % e )
    finally:
      session.close()




#   def putRequest( self, request ):
#     """ update or insert request into db
#
#     :param Request request: Request instance
#     """
#     query = "SELECT `RequestID`, `Status` from `Request` WHERE `RequestName` = '%s'" % request.RequestName
#     ret = self._transaction( query )
#     if not ret["OK"]:
#       self.log.error( "putRequest: %s" % ret["Message"] )
#       return ret
#
#     reqValues = ret["Value"].get( query )
#
#     if reqValues:
#       existingReqID = reqValues[0].get( "RequestID" )
#       status = reqValues[0].get( "Status" )
#     else:
#       existingReqID = None
#       status = None
#
#     if existingReqID and existingReqID != request.RequestID:
#       return S_ERROR( "putRequest: request '%s' already exists in the db (RequestID=%s)"\
#                        % ( request.RequestName, existingReqID ) )
#
#     if status == 'Canceled':
#       self.log.info( "Request %s was canceled, don't put it back" % request.RequestName )
#       return S_OK( request.RequestID )
#
#     reqSQL = request.toSQL()
#     if not reqSQL["OK"]:
#       return reqSQL
#     reqSQL = reqSQL["Value"]
#     putRequest = self._transaction( reqSQL )
#     if not putRequest["OK"]:
#       self.log.error( "putRequest: %s" % putRequest["Message"] )
#       return putRequest
#     lastrowid = putRequest["lastrowid"]
#     putRequest = putRequest["Value"]
#
#     cleanUp = request.cleanUpSQL()
#     if cleanUp:
#       dirty = self._transaction( cleanUp )
#       if not dirty["OK"]:
#         self.log.error( "putRequest: unable to delete dirty Operation records: %s" % dirty["Message"] )
#         return dirty
#
#     # # flag for a new request
#     isNew = False
#     # # set RequestID when necessary
#     if request.RequestID == 0:
#       isNew = True
#       request.RequestID = lastrowid
#
#     for operation in request:
#
#       cleanUp = operation.cleanUpSQL()
#       if cleanUp:
#         dirty = self._transaction( [ cleanUp ] )
#         if not dirty["OK"]:
#           self.log.error( "putRequest: unable to delete dirty File records: %s" % dirty["Message"] )
#           return dirty
#
#       opSQL = operation.toSQL()["Value"]
#       putOperation = self._transaction( opSQL )
#       if not putOperation["OK"]:
#         self.log.error( "putRequest: unable to put operation %d: %s" % ( request.indexOf( operation ),
#                                                                          putOperation["Message"] ) )
#         if isNew:
#           deleteRequest = self.deleteRequest( request.RequestName )
#           if not deleteRequest["OK"]:
#             self.log.error( "putRequest: unable to delete request '%s': %s"\
#                              % ( request.RequestName, deleteRequest["Message"] ) )
#             return deleteRequest
#         return putOperation
#       lastrowid = putOperation["lastrowid"]
#       putOperation = putOperation["Value"]
#       if operation.OperationID == 0:
#         operation.OperationID = lastrowid
#       filesToSQL = [ opFile.toSQL()["Value"] for opFile in operation ]
#       if filesToSQL:
#         putFiles = self._transaction( filesToSQL )
#         if not putFiles["OK"]:
#           self.log.error( "putRequest: unable to put files for operation %d: %s" % ( request.indexOf( operation ),
#                                                                                     putFiles["Message"] ) )
#           if isNew:
#             deleteRequest = self.deleteRequest( request.requestName )
#             if not deleteRequest["OK"]:
#               self.log.error( "putRequest: unable to delete request '%s': %s"\
#                               % ( request.RequestName, deleteRequest["Message"] ) )
#               return deleteRequest
#           return putFiles
#
#     return S_OK( request.RequestID )
  def putRequest( self, request ):
    """ update or insert request into db

    :param Request request: Request instance
    """
    
    session = self.DBSession( expire_on_commit = False )
    try:

      try:
        existingReqID, status = session.query( Request.RequestID, Request._Status )\
                                   .filter( Request.RequestName == request.RequestName )\
                                   .one()

        if existingReqID and existingReqID != request.RequestID:
          return S_ERROR( "putRequest: request '%s' already exists in the db (RequestID=%s)"\
                         % ( request.RequestName, existingReqID ) )
  
        if status == 'Canceled':
          self.log.info( "Request %s was canceled, don't put it back" % request.RequestName )
          return S_OK( request.RequestID )

      except NoResultFound, e:
        pass

    

      session.add( request )
      session.commit()
      session.expunge_all()
  
      return S_OK( request.RequestID )

    except Exception, e:
      session.rollback()
      self.log.exception( "putRequest: unexpected exception", lException = e )
      return S_ERROR( "putRequest: unexpected exception %s" % e )
    finally:
      session.close()

#   def getScheduledRequest( self, operationID ):
#     """ read scheduled request given its FTS operationID """
#     query = "SELECT `Request`.`RequestName` FROM `Request` JOIN `Operation` ON "\
#       "`Request`.`RequestID`=`Operation`.`RequestID` WHERE `OperationID` = %s;" % operationID
#     requestName = self._query( query )
#     if not requestName["OK"]:
#       self.log.error( "getScheduledRequest: %s" % requestName["Message"] )
#       return requestName
#     requestName = requestName["Value"]
#     if not requestName:
#       return S_OK()
#     return self.getRequest( requestName[0][0] )

  def getScheduledRequest( self, operationID ):
    session = self.DBSession()
    try:
      requestName = session.query( Request.RequestName )\
                           .join( Request.__operations__ )\
                           .filter( Operation.OperationID == operationID )\
                           .one()
      return self.getRequest( requestName[0] )
    except NoResultFound, e:
      return S_OK()
    finally:
      session.close()


  def getRequestName( self, requestID ):
    """ get Request.RequestName for a given Request.RequestID """

    session = self.DBSession()
    try:
      requestName = session.query( Request.RequestName ).filter( Request.RequestID == requestID ).one()
      return S_OK( requestName[0] )
    except NoResultFound, e:
      return S_ERROR( "getRequestName: no request found for RequestID=%s" % requestID )
    finally:
      session.close()


#   def getRequest( self, requestName = '', assigned = True ):
#     """ read request for execution
#
#     :param str requestName: request's name (default None)
#     """
#     requestID = None
#     log = self.log.getSubLogger( 'getRequest' if assigned else 'peekRequest' )
#     if requestName:
#       log.verbose( "selecting request '%s'%s" % ( requestName, ' (Assigned)' if assigned else '' ) )
#       reqIDQuery = "SELECT `RequestID`, `Status` FROM `Request` WHERE `RequestName` = '%s';" % str( requestName )
#       reqID = self._transaction( reqIDQuery )
#       if not reqID["OK"]:
#         log.error( reqID["Message"] )
#         return reqID
#       reqID = reqID["Value"].get( reqIDQuery, [] )
#       if reqID:
#         reqID = reqID[0]
#       else:
#         reqID = {}
#       requestID = reqID.get( "RequestID" )
#       status = reqID.get( "Status" )
#       if not all( ( requestID, status ) ):
#         return S_ERROR( "getRequest: request '%s' not exists" % requestName )
#       if requestID and status and status == "Assigned" and assigned:
#         return S_ERROR( "getRequest: status of request '%s' is 'Assigned', request cannot be selected" % requestName )
#     else:
#       reqIDsQuery = "SELECT `RequestID` FROM `Request` WHERE `Status` = 'Waiting' ORDER BY `LastUpdate` ASC LIMIT 100;"
#       reqAscIDs = self._transaction( reqIDsQuery )
#       if not reqAscIDs['OK']:
#         log.error( reqAscIDs["Message"] )
#         return reqAscIDs
#       reqIDs = set( [reqID['RequestID'] for reqID in reqAscIDs["Value"][reqIDsQuery]] )
#       reqIDsQuery = "SELECT `RequestID` FROM `Request` WHERE `Status` = 'Waiting' ORDER BY `LastUpdate` DESC LIMIT 50;"
#       reqDescIDs = self._transaction( reqIDsQuery )
#       if not reqDescIDs['OK']:
#         log.error( reqDescIDs["Message"] )
#         return reqDescIDs
#       reqIDs |= set( [reqID['RequestID'] for reqID in reqDescIDs["Value"][reqIDsQuery]] )
#       if not reqIDs:
#         return S_OK()
#       reqIDs = list( reqIDs )
#       random.shuffle( reqIDs )
#       requestID = reqIDs[0]
#
#     selectQuery = [ "SELECT * FROM `Request` WHERE `RequestID` = %s;" % requestID,
#                     "SELECT * FROM `Operation` WHERE `RequestID` = %s;" % requestID ]
#     selectReq = self._transaction( selectQuery )
#     if not selectReq["OK"]:
#       log.error( selectReq["Message"] )
#       return S_ERROR( selectReq["Message"] )
#     selectReq = selectReq["Value"]
#
#     request = Request( selectReq[selectQuery[0]][0] )
#     if not requestName:
#       log.verbose( "selected request '%s'%s" % ( request.RequestName, ' (Assigned)' if assigned else '' ) )
#     for records in sorted( selectReq[selectQuery[1]], key = lambda k: k["Order"] ):
#       # # order is ro, remove
#       del records["Order"]
#       operation = Operation( records )
#       getFilesQuery = "SELECT * FROM `File` WHERE `OperationID` = %s;" % operation.OperationID
#       getFiles = self._transaction( getFilesQuery )
#       if not getFiles["OK"]:
#         log.error( getFiles["Message"] )
#         return getFiles
#       getFiles = getFiles["Value"][getFilesQuery]
#       for getFile in getFiles:
#         getFileDict = dict( [ ( key, value ) for key, value in getFile.items() if value != None ] )
#         operation.addFile( File( getFileDict ) )
#       request.addOperation( operation )
#
#     if assigned:
#       setAssigned = self._transaction( "UPDATE `Request` SET `Status` = 'Assigned', `LastUpdate`=UTC_TIMESTAMP() WHERE RequestID = %s;" % requestID )
#       if not setAssigned["OK"]:
#         log.error( "%s" % setAssigned["Message"] )
#         return setAssigned
#
#     return S_OK( request )

  def getRequest( self, requestName = '', assigned = True ):
    """ read request for execution

    :param str requestName: request's name (default None)
    """

    # expire_on_commit is set to False so that we can still use the object after we close the session
    session = self.DBSession( expire_on_commit = False )
    log = self.log.getSubLogger( 'getRequest' if assigned else 'peekRequest' )

    requestID = None
    try:

      if requestName:

        log.verbose( "selecting request '%s'%s" % ( requestName, ' (Assigned)' if assigned else '' ) )
        status = None
        try:
          requestID, status = session.query( Request.RequestID, Request._Status )\
                                     .filter( Request.RequestName == requestName )\
                                     .one()
        except NoResultFound, e:
          return S_ERROR( "getRequest: request '%s' not exists" % requestName )
  
        if requestID and status and status == "Assigned" and assigned:
          return S_ERROR( "getRequest: status of request '%s' is 'Assigned', request cannot be selected" % requestName )

      else:
        reqIDs = set()
        try:
          reqAscIDs = session.query( Request.RequestID )\
                             .filter( Request._Status == 'Waiting' )\
                             .order_by( Request._LastUpdate )\
                             .limit( 100 )\
                             .all()

          reqIDs = set( [reqID[0] for reqID in reqAscIDs] )

          reqDescIDs = session.query( Request.RequestID )\
                              .filter( Request._Status == 'Waiting' )\
                              .order_by( Request._LastUpdate.desc() )\
                              .limit( 50 )\
                              .all()

          reqIDs |= set( [reqID[0] for reqID in reqDescIDs] )
        # No Waiting requests
        except NoResultFound, e:
          return S_OK()
  
        reqIDs = list( reqIDs )
        random.shuffle( reqIDs )
        requestID = reqIDs[0]


      # If we are here, the request MUST exist, so no try catch
      # the joinedload_all is to force the non-lazy loading of all the attributes, especially _parent
      request = session.query( Request )\
                       .options( joinedload_all( '__operations__.__files__' ) )\
                       .filter( Request.RequestID == requestID )\
                       .one()
  
      if not requestName:
        log.verbose( "selected request '%s'%s" % ( request.RequestName, ' (Assigned)' if assigned else '' ) )
  
  
      if assigned:
        session.execute( update( Request )\
                         .where( Request.RequestID == requestID )\
                         .values( {Request._Status : 'Assigned'} )
                       )
        session.commit()

      session.expunge_all()
      return S_OK( request )
    
    except Exception, e:
      session.rollback()
      log.exception( "getRequest: unexpected exception", lException = e )
      return S_ERROR( "getRequest: unexpected exception : %s" % e )
    finally:
      session.close()


#   def getBulkRequests( self, numberOfRequest = 10, assigned = True ):
#     """ read as many requests as requested for execution
#
#     :param int numberOfRequest: Number of Request we want (default 10)
#     :param bool assigned: if True, the status of the selected requests are set to assign
#
#     :returns a dictionary of Request objects indexed on the RequestID
#
#     """
#
#     # r_RequestID : RequestID, r_LastUpdate : LastUpdate...
#     requestAttrDict = dict ( ("r_%s"%r, r) for r in Request.tableDesc()["Fields"])
#     # o_RequestID : RequestID, o_OperationID : OperationID...
#     operationAttrDict = dict ( ("o_%s"%o, o) for o in Operation.tableDesc()["Fields"])
#     # f_OperationID : OperationID, f_FileID : FileID...
#     fileAttrDict = dict ( ("f_%s"%f, f) for f in File.tableDesc()["Fields"])
#
#     # o.OperationID as o_OperationID, ..., r_RequestID, ..., f_FileID, ...
#     allFieldsStr = ",".join([ "o.%s as %s"%(operationAttrDict[o], o) for o in operationAttrDict]\
#                             + requestAttrDict.keys() + fileAttrDict.keys())
#
#     # RequestID as r_RequestID, LastUpdate as r_LastUpdate, ...
#     requestAttrStr = ",".join([ "%s as %s"%(requestAttrDict[r], r) for r in requestAttrDict])
#
#     # OperationID as f_OperationID, FileID as f_FileID...
#     fileAttrStr = ",".join([ "%s as %s"%(fileAttrDict[f], f) for f in fileAttrDict])
#
#
#     # Selects all the Request (limited to numberOfRequest, sorted by LastUpdate) , Operation and File information.
#     # The entries are sorted by the LastUpdate of the Requests, RequestID if several requests were update the last time
#     # at the same time, and finally according to the Operation Order
#     query = "SELECT %s FROM Operation o \
#             INNER JOIN (SELECT %s FROM Request WHERE Status = 'Waiting' ORDER BY `LastUpdate` ASC limit %s) r\
#             ON r_RequestID = o.RequestID\
#             INNER JOIN (SELECT %s from File) f ON f_OperationId = o.OperationId\
#             ORDER BY r_LastUpdate, r_RequestId, o_Order;"\
#              % ( allFieldsStr, requestAttrStr, numberOfRequest, fileAttrStr )
#
#     print query
#     queryResult = self._transaction( query )
#     if not queryResult["OK"]:
#       self.log.error( "RequestDB.getRequests: %s" % queryResult["Message"] )
#       return queryResult
#
#     allResults = queryResult["Value"][query]
#
#     # We now construct a dict of Request indexed by their ID, and the same for Operation
#
#     requestDict = {}
#     operationDict = {}
#     for entry in allResults:
#       requestID = int( entry["r_RequestID"] )
#       # If the object already exists, we get it, otherwise we create it and assign it
#       requestObj = requestDict.setdefault( requestID, Request( dict( ( requestAttrDict[r], entry[r] ) for r in requestAttrDict ) ) )
#
#       operationID = int( entry["o_OperationID"] )
#       operationObj = operationDict.get( operationID, None )
#
#       # If the Operation object does not exist yet, we create it, and add it to the Request
#       if not operationObj:
#         operationObj = Operation( dict( ( operationAttrDict[o], entry[o] ) for o in operationAttrDict ) )
#         operationDict[operationID ] = operationObj
#         requestObj.addOperation( operationObj )
#
#       fileObj = File( dict( ( fileAttrDict[f], entry[f] ) for f in fileAttrDict ) )
#       operationObj.addFile( fileObj )
#
#
#     if assigned and len( requestDict ):
#       listOfReqId = ",".join( str( rId ) for rId in requestDict )
#       setAssigned = self._transaction( "UPDATE `Request` SET `Status` = 'Assigned' WHERE RequestID IN (%s);" % listOfReqId )
#       if not setAssigned["OK"]:
#         self.log.error( "getRequests: %s" % setAssigned["Message"] )
#         return setAssigned
#
#     return S_OK( requestDict )

  def getBulkRequests( self, numberOfRequest = 10, assigned = True ):
    """ read as many requests as requested for execution

    :param int numberOfRequest: Number of Request we want (default 10)
    :param bool assigned: if True, the status of the selected requests are set to assign

    :returns a dictionary of Request objects indexed on the RequestID

    """
    
    # expire_on_commit is set to False so that we can still use the object after we close the session
    session = self.DBSession( expire_on_commit = False )
    log = self.log.getSubLogger( 'getBulkRequest' if assigned else 'peekBulkRequest' )

    requestDict = {}

    try:

      # If we are here, the request MUST exist, so no try catch
      # the joinedload_all is to force the non-lazy loading of all the attributes, especially _parent
      try:
        requests = session.query( Request )\
                          .options( joinedload_all( '__operations__.__files__' ) )\
                          .filter( Request._Status == 'Waiting' )\
                          .order_by( Request._LastUpdate )\
                          .limit( numberOfRequest )\
                          .all()
        requestDict = dict((req.RequestID, req) for req in requests)
      # No Waiting requests
      except NoResultFound, e:
        pass
      
      if assigned and requestDict:
        session.execute( update( Request )\
                         .where( Request.RequestID.in_( requestDict.keys() ) )\
                         .values( {Request._Status : 'Assigned'} )
                       )
        session.commit()

      session.expunge_all()

    except Exception, e:
      session.rollback()
      log.exception( "unexpected exception", lException = e )
      return S_ERROR( "getBulkRequest: unexpected exception : %s" % e )
    finally:
      session.close()

    return S_OK( requestDict )



  def peekRequest( self, requestName ):
    """ get request (ro), no update on states

    :param str requestName: Request.RequestName
    """
    return self.getRequest( requestName, False )

#   def getRequestNamesList( self, statusList = None, limit = None, since = None, until = None ):
#     """ select requests with status in :statusList: """
#     statusList = statusList if statusList else list( Request.FINAL_STATES )
#     limit = limit if limit else 100
#     sinceReq = " AND LastUpdate > %s " % since  if since else ""
#     untilReq = " AND LastUpdate < %s " % until if until else ""
#     query = "SELECT `RequestName`, `Status`, `LastUpdate` FROM `Request` WHERE "\
#       " `Status` IN (%s) %s %s ORDER BY `LastUpdate` ASC LIMIT %s;" % ( stringListToString( statusList ), sinceReq, untilReq, limit )
#     reqNamesList = self._query( query )
#     if not reqNamesList["OK"]:
#       self.log.error( "getRequestNamesList: %s" % reqNamesList["Message"] )
#       return reqNamesList
#     reqNamesList = reqNamesList["Value"]
#     return S_OK( [ reqName for reqName in reqNamesList] )


  def getRequestNamesList( self, statusList = None, limit = None, since = None, until = None ):
    """ select requests with status in :statusList: """
    statusList = statusList if statusList else list( Request.FINAL_STATES )
    limit = limit if limit else 100
    session = self.DBSession()
    requests = []
    try:
      reqQuery = session.query( Request.RequestName )\
                        .filter( Request._Status.in_( statusList ) )
      if since:
        reqQuery = reqQuery.filter( Request._LastUpdate > since )
      if until:
        reqQuery = reqQuery.filter( Request._LastUpdate < until )

      reqQuery = reqQuery.order_by( Request._LastUpdate )\
                         .limit( limit )
      requests = [reqNameTuple[0] for reqNameTuple in reqQuery.all()]

    except Exception, e:
      session.rollback()
      self.log.exception( "getRequestNamesList: unexpected exception", lException = e )
      return S_ERROR( "getRequestNamesList: unexpected exception : %s" % e )
    finally:
      session.close()

    return S_OK( requests )



#   def deleteRequest( self, requestName ):
#     """ delete request given its name
#
#     :param str requestName: request.RequestName
#     :param mixed connection: connection to use if any
#     """
#     requestIDs = self._transaction(
#       "SELECT r.RequestID, o.OperationID FROM `Request` r LEFT JOIN `Operation` o "\
#         "ON r.RequestID = o.RequestID WHERE `RequestName` = '%s'" % requestName )
#
#     if not requestIDs["OK"]:
#       self.log.error( "deleteRequest: unable to read RequestID and OperationIDs: %s" % requestIDs["Message"] )
#       return requestIDs
#     requestIDs = requestIDs["Value"]
#     trans = []
#     requestID = None
#     for records in requestIDs.values():
#       for record in records:
#         requestID = record["RequestID"] if record["RequestID"] else None
#         operationID = record["OperationID"] if record["OperationID"] else None
#         if operationID and requestID:
#           trans.append( "DELETE FROM `File` WHERE `OperationID` = %s;" % operationID )
#           trans.append( "DELETE FROM `Operation` WHERE `RequestID` = %s AND `OperationID` = %s;" % ( requestID,
#                                                                                                     operationID ) )
#     # # last bit: request itself
#     if requestID:
#       trans.append( "DELETE FROM `Request` WHERE `RequestID` = %s;" % requestID )
#
#     delete = self._transaction( trans )
#     if not delete["OK"]:
#       self.log.error( "deleteRequest: unable to delete request '%s': %s" % ( requestName, delete["Message"] ) )
#       return delete
#     return S_OK()

  def deleteRequest( self, requestName ):
    """ delete request given its name

    :param str requestName: request.RequestName
    :param mixed connection: connection to use if any
    """
    
    session = self.DBSession()

    try:
      session.query( Request ).filter( Request.RequestName == requestName ).delete()
      session.commit()
    except Exception, e:
      session.rollback()
      self.log.exception( "deleteRequest: unexpected exception", lException = e )
      return S_ERROR( "deleteRequest: unexpected exception : %s" % e )
    finally:
      session.close()

    return S_OK()



#
#   def getRequestProperties( self, requestName, columnNames ):
#     """ submit query """
#     return self._query( self._getRequestProperties( requestName, columnNames ) )
#
#   def _getRequestProperties( self, requestName, columnNames = None ):
#     """ select :columnNames: from Request table  """
#     columnNames = columnNames if columnNames else Request.tableDesc()["Fields"].keys()
#     columnNames = ",".join( [ '`%s`' % str( columnName ) for columnName in columnNames ] )
#     return "SELECT %s FROM `Request` WHERE `RequestName` = '%s';" % ( columnNames, requestName )
#
#   def _getOperationProperties( self, operationID, columnNames = None ):
#     """ select :columnNames: from Operation table  """
#     columnNames = columnNames if columnNames else Operation.tableDesc()["Fields"].keys()
#     columnNames = ",".join( [ '`%s`' % str( columnName ) for columnName in columnNames ] )
#     return "SELECT %s FROM `Operation` WHERE `OperationID` = %s;" % ( columnNames, int( operationID ) )
#
#   def _getFileProperties( self, fileID, columnNames = None ):
#     """ select :columnNames: from File table  """
#     columnNames = columnNames if columnNames else File.tableDesc()["Fields"].keys()
#     columnNames = ",".join( [ '`%s`' % str( columnName ) for columnName in columnNames ] )
#     return "SELECT %s FROM `File` WHERE `FileID` = %s;" % ( columnNames, int( fileID ) )

#   def getDBSummary( self ):
#     """ get db summary """
#
#     # # this will be returned
#     retDict = { "Request" : {}, "Operation" : {}, "File" : {} }
#     transQueries = { "SELECT `Status`, COUNT(`Status`) FROM `Request` GROUP BY `Status`;" : "Request",
#                      "SELECT `Type`,`Status`,COUNT(`Status`) FROM `Operation` GROUP BY `Type`,`Status`;" : "Operation",
#                      "SELECT `Status`, COUNT(`Status`) FROM `File` GROUP BY `Status`;" : "File" }
#     ret = self._transaction( transQueries.keys() )
#     if not ret["OK"]:
#       self.log.error( "getDBSummary: %s" % ret["Message"] )
#       return ret
#     ret = ret["Value"]
#     for k, v in ret.items():
#       if transQueries[k] == "Request":
#         for aDict in v:
#           status = aDict.get( "Status" )
#           count = aDict.get( "COUNT(`Status`)" )
#           if status not in retDict["Request"]:
#             retDict["Request"][status] = 0
#           retDict["Request"][status] += count
#       elif transQueries[k] == "File":
#         for aDict in v:
#           status = aDict.get( "Status" )
#           count = aDict.get( "COUNT(`Status`)" )
#           if status not in retDict["File"]:
#             retDict["File"][status] = 0
#           retDict["File"][status] += count
#       else:  # # operation
#         for aDict in v:
#           status = aDict.get( "Status" )
#           oType = aDict.get( "Type" )
#           count = aDict.get( "COUNT(`Status`)" )
#           if oType not in retDict["Operation"]:
#             retDict["Operation"][oType] = {}
#           if status not in retDict["Operation"][oType]:
#             retDict["Operation"][oType][status] = 0
#           retDict["Operation"][oType][status] += count
#     return S_OK( retDict )

  def getDBSummary( self ):
    """ get db summary """
    # # this will be returned
    retDict = { "Request" : {}, "Operation" : {}, "File" : {} }
 
    session = self.DBSession()
 
    try:
      requestQuery = session.query(Request._Status, func.count(Request.RequestID)).group_by(Request._Status).all()
      for status, count in requestQuery:
        retDict["Request"][status] = count
 
      operationQuery = session.query(Operation.Type, Operation._Status, func.count(Operation.OperationID))\
                              .group_by(Operation.Type, Operation._Status).all()
      for oType, status, count in operationQuery:
        retDict['Operation'].setdefault( oType, {} )[status] = count
      
      
      fileQuery = session.query(File._Status, func.count(File.FileID)).group_by(File._Status).all()
      for status, count in fileQuery:
        retDict["File"][status] = count
 
    except Exception, e:
      self.log.exception( "getDBSummary: unexpected exception", lException = e )
      return S_ERROR( "getDBSummary: unexpected exception : %s" % e )
    finally:
      session.close()

    return S_OK( retDict )


  def getRequestSummaryWeb( self, selectDict, sortList, startItem, maxItems ):
    """ get db summary for web

    :param dict selectDict: whatever
    :param list sortList: whatever
    :param int startItem: limit
    :param int maxItems: limit


    """
    resultDict = {}
    rparameterList = [ 'RequestID', 'RequestName', 'JobID', 'OwnerDN', 'OwnerGroup']
    sparameterList = [ 'Type', 'Status', 'Operation']
    parameterList = rparameterList + sparameterList + [ "Error", "CreationTime", "LastUpdate"]
    # parameterList.append( 'Error' )
    # parameterList.append( 'CreationTime' )
    # parameterList.append( 'LastUpdateTime' )

    req = "SELECT R.RequestID, R.RequestName, R.JobID, R.OwnerDN, R.OwnerGroup,"
    req += "O.Type, O.Status, O.Type, O.Error, O.CreationTime, O.LastUpdate FROM Request as R, Operation as O "

    new_selectDict = {}
    older = None
    newer = None
    for key, value in selectDict.items():
      if key in rparameterList:
        new_selectDict['R.' + key] = value
      elif key in sparameterList:
        new_selectDict['O.' + key] = value
      elif key == 'ToDate':
        older = value
      elif key == 'FromDate':
        newer = value

    condition = ''
    if new_selectDict or older or newer:
      condition = self.__buildCondition( new_selectDict, older = older, newer = newer )
      req += condition

    if condition:
      req += " AND R.RequestID=O.RequestID"
    else:
      req += " WHERE R.RequestID=O.RequestID"

    if sortList:
      req += " ORDER BY %s %s" % ( sortList[0][0], sortList[0][1] )
    result = self._query( req )
    if not result['OK']:
      return result

    if not result['Value']:
      resultDict['ParameterNames'] = parameterList
      resultDict['Records'] = []
      return S_OK( resultDict )

    nRequests = len( result['Value'] )

    if startItem <= len( result['Value'] ):
      firstIndex = startItem
    else:
      return S_ERROR( 'Requested index out of range' )

    if ( startItem + maxItems ) <= len( result['Value'] ):
      secondIndex = startItem + maxItems
    else:
      secondIndex = len( result['Value'] )

    records = []
    columnWidth = [ 0 for x in range( len( parameterList ) ) ]
    for i in range( firstIndex, secondIndex ):
      row = result['Value'][i]
      records.append( [ str( x ) for x in row] )
      for ind in range( len( row ) ):
        if len( str( row[ind] ) ) > columnWidth[ind]:
          columnWidth[ind] = len( str( row[ind] ) )

    resultDict['ParameterNames'] = parameterList
    resultDict['ColumnWidths'] = columnWidth
    resultDict['Records'] = records
    resultDict['TotalRecords'] = nRequests

    return S_OK( resultDict )

#   def getRequestNamesForJobs( self, jobIDs ):
#     """ read request names for jobs given jobIDs
#
#     :param list jobIDs: list of jobIDs
#     """
#     self.log.debug( "getRequestForJobs: got %s jobIDs to check" % str( jobIDs ) )
#     if not jobIDs:
#       return S_ERROR( "Must provide jobID list as argument." )
#     if type( jobIDs ) in ( long, int ):
#       jobIDs = [ jobIDs ]
#     jobIDs = list( set( [ int( jobID ) for jobID in jobIDs ] ) )
#     reqDict = { "Successful": {}, "Failed": {} }
#     # # filter out 0
#     jobIDsStr = ",".join( [ str( jobID ) for jobID in jobIDs if jobID ] )
#     # # request names
#     requestNames = "SELECT `RequestName`, `JobID` FROM `Request` WHERE `JobID` IN (%s);" % jobIDsStr
#     requestNames = self._query( requestNames )
#     if not requestNames["OK"]:
#       self.log.error( "getRequestsForJobs: %s" % requestNames["Message"] )
#       return requestNames
#     requestNames = requestNames["Value"]
#     for requestName, jobID in requestNames:
#       reqDict["Successful"][jobID] = requestName
#     reqDict["Failed"] = dict.fromkeys( [ jobID for jobID in jobIDs if jobID not in reqDict["Successful"] ],
#                                        "Request not found" )
#     return S_OK( reqDict )

  def getRequestNamesForJobs( self, jobIDs ):
    """ read request names for jobs given jobIDs

    :param list jobIDs: list of jobIDs
    """
    self.log.debug( "getRequestForJobs: got %s jobIDs to check" % str( jobIDs ) )
    if not jobIDs:
      return S_ERROR( "Must provide jobID list as argument." )
    if type( jobIDs ) in ( long, int ):
      jobIDs = [ jobIDs ]
    jobIDs = set( jobIDs )

    reqDict = { "Successful": {}, "Failed": {} }

    session = self.DBSession()

    try:
      ret = session.query( Request.JobID, Request.RequestName ).filter( Request.JobID.in_( jobIDs ) ).all()
      reqDict['Successful'] = dict((jobId, reqName) for jobId, reqName in ret)
      reqDict['Failed'] = dict( (jobid, 'Request not found') for jobid in jobIDs - set(reqDict['Successful']))
    except Exception, e:
      self.log.exception( "getRequestNamesForJobs: unexpected exception", lException = e )
      return S_ERROR( "getRequestNamesForJobs: unexpected exception : %s" % e )
    finally:
      session.close()

    return S_OK( reqDict )


#   def readRequestsForJobs( self, jobIDs = None ):
#     """ read request for jobs
#
#     :param list jobIDs: list of JobIDs
#     :return: S_OK( "Successful" : { jobID1 : Request, jobID2: Request, ... }
#                    "Failed" : { jobID3: "error message", ... } )
#     """
#     self.log.debug( "readRequestForJobs: got %s jobIDs to check" % str( jobIDs ) )
#     requestNames = self.getRequestNamesForJobs( jobIDs )
#     if not requestNames["OK"]:
#       self.log.error( "readRequestForJobs: %s" % requestNames["Message"] )
#       return requestNames
#     requestNames = requestNames["Value"]
#     # # this will be returned
#     retDict = { "Failed": requestNames["Failed"], "Successful": {} }
#
#     self.log.debug( "readRequestForJobs: got %d request names" % len( requestNames["Successful"] ) )
#     for jobID in requestNames['Successful']:
#       request = self.peekRequest( requestNames['Successful'][jobID] )
#       if not request["OK"]:
#         retDict["Failed"][jobID] = request["Message"]
#         continue
#       retDict["Successful"][jobID] = request["Value"]
#     return S_OK( retDict )
  def readRequestsForJobs( self, jobIDs = None ):
    """ read request for jobs

    :param list jobIDs: list of JobIDs
    :return: S_OK( "Successful" : { jobID1 : Request, jobID2: Request, ... }
                   "Failed" : { jobID3: "error message", ... } )
    """
    self.log.debug( "readRequestForJobs: got %s jobIDs to check" % str( jobIDs ) )
    if not jobIDs:
      return S_ERROR( "Must provide jobID list as argument." )
    if type( jobIDs ) in ( long, int ):
      jobIDs = [ jobIDs ]
    jobIDs = set( jobIDs )

    reqDict = { "Successful": {}, "Failed": {} }

    # expire_on_commit is set to False so that we can still use the object after we close the session
    session = self.DBSession( expire_on_commit = False )

    try:
      ret = session.query( Request.JobID, Request )\
                   .options( joinedload_all( '__operations__.__files__' ) )\
                   .filter( Request.JobID.in_( jobIDs ) ).all()
      reqDict['Successful'] = dict( ( jobId, reqObj ) for jobId, reqObj in ret )
      reqDict['Failed'] = dict( ( jobid, 'Request not found' ) for jobid in jobIDs - set( reqDict['Successful'] ) )
      session.expunge_all()
    except Exception, e:
      self.log.exception( "readRequestsForJobs: unexpected exception", lException = e )
      return S_ERROR( "readRequestsForJobs: unexpected exception : %s" % e )
    finally:
      session.close()

    return S_OK( reqDict )

#   def getRequestStatus( self, requestName ):
#     """ get request status for a given request name """
#     self.log.debug( "getRequestStatus: checking status for '%s' request" % requestName )
#     query = "SELECT `Status` FROM `Request` WHERE `RequestName` = '%s'" % requestName
#     query = self._query( query )
#     if not query["OK"]:
#       self.log.error( "getRequestStatus: %s" % query["Message"] )
#       return query
#     if query['Value'] and query['Value'][0]:
#       requestStatus = query['Value'][0][0]
#     else:
#       return S_ERROR( "Request %s does not exist" % requestName )
#     return S_OK( requestStatus )

  def getRequestStatus( self, requestName ):
    """ get request status for a given request name """
    self.log.debug( "getRequestStatus: checking status for '%s' request" % requestName )
    session = self.DBSession()
    try:
      status = session.query( Request._Status ).filter( Request.RequestName == requestName ).one()
    except  NoResultFound, e:
      return S_ERROR( "Request %s does not exist" % requestName )
    finally:
      session.close()
    return S_OK( status[0] )


#   def getRequestFileStatus( self, requestName, lfnList ):
#     """ get status for files in request given its name
#
#     :param str requestName: Request.RequestName
#     :param list lfnList: list of LFNs
#     """
#     if type( requestName ) == int:
#       requestName = self.getRequestName( requestName )
#       if not requestName["OK"]:
#         self.log.error( "getRequestFileStatus: %s" % requestName["Message"] )
#         return requestName
#       else:
#         requestName = requestName["Value"]
#
#     req = self.peekRequest( requestName )
#     if not req["OK"]:
#       self.log.error( "getRequestFileStatus: %s" % req["Message"] )
#       return req
#
#     req = req["Value"]
#     res = dict.fromkeys( lfnList, "UNKNOWN" )
#     for op in req:
#       for opFile in op:
#         if opFile.LFN in lfnList:
#           res[opFile.LFN] = opFile.Status
#     return S_OK( res )

  def getRequestFileStatus( self, requestName, lfnList ):
    """ get status for files in request given its name

    :param str requestName: Request.RequestName
    :param list lfnList: list of LFNs
    """
    if type( requestName ) == int:
      requestName = self.getRequestName( requestName )
      if not requestName["OK"]:
        self.log.error( "getRequestFileStatus: %s" % requestName["Message"] )
        return requestName
      else:
        requestName = requestName["Value"]

    session = self.DBSession()
    try:
      res = dict.fromkeys( lfnList, "UNKNOWN" )
      requestRet = session.query( File._LFN, File._Status )\
                       .join( Request.__operations__ )\
                       .join( Operation.__files__ )\
                       .filter( Request.RequestName == requestName )\
                       .filter( File._LFN.in_( lfnList ) )\
                       .all()

      for lfn, status in requestRet:
        res[lfn] = status
      return S_OK( res )

    except Exception, e:
      self.log.exception( "getRequestFileStatus: unexpected exception", lException = e )
      return S_ERROR( "getRequestFileStatus: unexpected exception : %s" % e )
    finally:
      session.close()


#   def getRequestInfo( self, requestName ):
#     """ get request info given Request.RequestID """
#     if type( requestName ) == int:
#       requestName = self.getRequestName( requestName )
#       if not requestName["OK"]:
#         self.log.error( "getRequestInfo: %s" % requestName["Message"] )
#         return requestName
#       else:
#         requestName = requestName["Value"]
#     requestInfo = self.getRequestProperties( requestName, [ "RequestID", "Status", "RequestName", "JobID",
#                                                             "OwnerDN", "OwnerGroup", "DIRACSetup", "SourceComponent",
#                                                             "CreationTime", "SubmitTime", "lastUpdate" ] )
#     if not requestInfo["OK"]:
#       self.log.error( "getRequestInfo: %s" % requestInfo["Message"] )
#       return requestInfo
#     requestInfo = requestInfo["Value"][0]
#     return S_OK( requestInfo )


  def getRequestInfo( self, requestNameOrID ):
    """ get request info given Request.RequestID """

    session = self.DBSession()

    try:

      requestInfoQuery = session.query( Request.RequestID, Request._Status, Request.RequestName,
                                        Request.JobID, Request.OwnerDN, Request.OwnerGroup,
                                        Request.DIRACSetup, Request.SourceComponent, Request._CreationTime,
                                        Request._SubmitTime, Request._LastUpdate )

      if type( requestNameOrID ) == int:
        requestInfoQuery = requestInfoQuery.filter( Request.RequestID == requestNameOrID )
      else:
        requestInfoQuery = requestInfoQuery.filter( Request.RequestName == requestNameOrID )

      try:
        requestInfo = requestInfoQuery.one()
      except NoResultFound, e:
        return S_ERROR( 'No such request' )

      return S_OK( tuple( requestInfo ) )

    except Exception, e:
      self.log.exception( "getRequestInfo: unexpected exception", lException = e )
      return S_ERROR( "getRequestInfo: unexpected exception : %s" % e )

    finally:
      session.close()

  def getDigest( self, requestName ):
    """ get digest for request given its name

    :param str requestName: request name
    """
    self.log.debug( "getDigest: will create digest for request '%s'" % requestName )
    request = self.getRequest( requestName, False )
    if not request["OK"]:
      self.log.error( "getDigest: %s" % request["Message"] )
    request = request["Value"]
    if not isinstance( request, Request ):
      self.log.info( "getDigest: request '%s' not found" )
      return S_OK()
    return request.getDigest()

#   @staticmethod
#   def __buildCondition( condDict, older = None, newer = None ):
#     """ build SQL condition statement from provided condDict
#        and other extra conditions
#
#        blindly copied from old code, hope it works
#     """
#     condition = ''
#     conjunction = "WHERE"
#     if condDict != None:
#       for attrName, attrValue in condDict.items():
#         if type( attrValue ) == list:
#           multiValue = ','.join( ['"' + x.strip() + '"' for x in attrValue] )
#           condition = ' %s %s %s in (%s)' % ( condition,
#                                               conjunction,
#                                               str( attrName ),
#                                               multiValue )
#         else:
#           condition = ' %s %s %s=\'%s\'' % ( condition,
#                                              conjunction,
#                                              str( attrName ),
#                                              str( attrValue ) )
#         conjunction = "AND"
#
#     if older:
#       condition = ' %s %s O.LastUpdate < \'%s\'' % ( condition,
#                                                  conjunction,
#                                                  str( older ) )
#       conjunction = "AND"
#
#     if newer:
#       condition = ' %s %s O.LastUpdate >= \'%s\'' % ( condition,
#                                                  conjunction,
#                                                  str( newer ) )
#
#     return condition


