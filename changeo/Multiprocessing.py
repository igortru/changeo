"""
Multiprocessing functions
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from changeo import __version__, __date__

# Imports
import os
import sys
from collections import OrderedDict
from time import time

# Presto and changeo imports
from presto.IO import getOutputHandle, printProgress, printLog
from changeo.Defaults import default_out_args
from changeo.IO import countDbFile, getDbFields
from changeo.Receptor import Receptor
from changeo.Parsers import AIRRReader, AIRRWriter, ChangeoReader, ChangeoWriter


class DbData:
    """
    A class defining data objects for worker processes

    Attributes:
      id : result identifier
      data : list of data records
      valid : True if preprocessing was successfull and data should be processed
    """
    # Instantiation
    def __init__(self, key, records):
        self.id = key
        self.data = records
        self.valid = (key is not None and records is not None)

    # Boolean evaluation
    def __bool__(self):
        return self.valid

    # Length evaluation
    def __len__(self):
        if isinstance(self.data, Receptor):
            return 1
        elif self.data is None:
            return 0
        else:
            return len(self.data)


class DbResult:
    """
    A class defining result objects for collector processes

    Attributes:
      id : result identifier
      data : list of original data records
      results: list of processed records
      data_pass: list of records that pass filtering for workers that split data before processing
      data_fail: list of records that failed filtering for workers that split data before processing
      valid : True if processing was successful and results should be written
      log : OrderedDict of log items
    """
    # Instantiation
    def __init__(self, key, records):
        self.id = key
        self.data = records
        self.results = None
        self.data_pass = records
        self.data_fail = None
        self.valid = False
        self.log = OrderedDict([('ID', key)])

    # Boolean evaluation
    def __bool__(self):
        return self.valid

    # Length evaluation
    def __len__(self):
        if isinstance(self.results, Receptor):
            return 1
        elif self.results is None:
            return 0
        else:
            return len(self.results)

    # Set data_count to number of data records
    @property
    def data_count(self):
        if isinstance(self.data, Receptor):
            return 1
        elif self.data is None:
            return 0
        else:
            return len(self.data)


def feedDbQueue(alive, data_queue, db_file, reader=ChangeoReader, group_func=None, group_args={}):
    """
    Feeds the data queue with Ig records

    Arguments:
      alive : multiprocessing.Value boolean controlling whether processing continues
              if False exit process
      data_queue : multiprocessing.Queue to hold data for processing
      db_file : database file
      reader : database reader class
      group_func : function to use for grouping records
      group_args : dictionary of arguments to pass to group_func

    Returns:
      None
    """
    # Open input file and perform grouping
    try:
        # Iterate over records and assign groups
        db_handle = open(db_file, 'rt')
        db_iter = reader(db_handle)
        if group_func is not None:
            group_dict = group_func(db_iter, **group_args)
            group_iter = iter(group_dict.items())
        else:
            group_iter = ((r.sequence_id, r) for r in db_iter)
    except:
        alive.value = False
        raise

    # Add groups to data queue
    try:
        # Iterate over groups and feed data queue
        while alive.value:
            # Get data from queue
            if data_queue.full():  continue
            else:  data = next(group_iter, None)
            # Exit upon reaching end of iterator
            if data is None:  break

            # Feed queue
            data_queue.put(DbData(*data))
        else:
            sys.stderr.write('PID %s:  Error in sibling process detected. Cleaning up.\n' \
                             % os.getpid())
            return None
    except:
        #sys.stderr.write('Exception in feeder queue feeding step\n')
        alive.value = False
        raise

    return None


def processDbQueue(alive, data_queue, result_queue, process_func, process_args={},
                   filter_func=None, filter_args={}):
    """
    Pulls from data queue, performs calculations, and feeds results queue

    Arguments:
      alive : multiprocessing.Value boolean controlling whether processing
            continues; when False function returns
      data_queue : multiprocessing.Queue holding data to process
      result_queue : multiprocessing.Queue to hold processed results
      process_func : function to use for processing sequences
      process_args : dictionary of arguments to pass to process_func
      filter_func : function to use for filtering sequences before processing
      filter_args : dictionary of arguments to pass to filter_func

    Returns:
      None
    """
    try:
        # Iterator over data queue until sentinel object reached
        while alive.value:
            # Get data from queue
            if data_queue.empty():  continue
            else:  data = data_queue.get()
            # Exit upon reaching sentinel
            if data is None:  break

            # Perform work
            if filter_func is None:
                result = process_func(data, **process_args)
            else:
                result = filter_func(data, **filter_args)
                result = process_func(result, **process_args)

            # Feed results to result queue
            result_queue.put(result)
        else:
            sys.stderr.write('PID %s:  Error in sibling process detected. Cleaning up.\n' \
                             % os.getpid())
            return None
    except:
        alive.value = False
        sys.stderr.write('Error processing data with ID: %s.\n' % str(data.id))
        raise

    return None


def collectDbQueue(alive, result_queue, collect_queue, db_file, label, fields,
                   writer=ChangeoWriter, out_args=default_out_args):
    """
    Pulls from results queue, assembles results and manages log and file IO

    Arguments:
      alive : multiprocessing.Value boolean controlling whether processing
              continues; when False function returns.
      result_queue : multiprocessing.Queue holding worker results.
      collect_queue : multiprocessing.Queue to store collector return values.
      db_file : database file name.
      label : task label used to tag the output files.
      fields : list of output fields.
      writer : writer class.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      None : Adds a dictionary with key value pairs to collect_queue containing
            'log' defining a log object,
            'out_files' defining the output file names
    """
    # Wrapper for opening handles and writers
    def _open(x, fields=fields, writer=writer, label=label):
        handle = getOutputHandle(db_file,
                                 out_label='%s-%s' % (label, x),
                                 out_dir=out_args['out_dir'],
                                 out_name=out_args['out_name'],
                                 out_type='tsv')
        return handle, writer(handle, fields=fields)

    try:
        # Count input
        result_count = countDbFile(db_file)

        # Define log handle
        if out_args['log_file'] is None:
            log_handle = None
        else:
            log_handle = open(out_args['log_file'], 'w')
    except:
        alive.value = False
        raise

    try:
        # Initialize handles, writers and counters
        pass_handle, pass_writer = None, None
        fail_handle, fail_writer = None, None
        set_count = rec_count = pass_count = fail_count = 0
        start_time = time()

        # Iterator over results queue until sentinel object reached
        while alive.value:
            # Get result from queue
            if result_queue.empty():  continue
            else:  result = result_queue.get()
            # Exit upon reaching sentinel
            if result is None:  break

            # Print progress for previous iteration
            printProgress(rec_count, result_count, 0.05, start_time)

            # Update counts for current iteration
            set_count += 1
            rec_count += result.data_count

            # Write log
            if result.log is not None:
                printLog(result.log, handle=log_handle)

            # Write passing results
            if result:
                # Open pass file and define writer object
                if pass_writer is None:
                    pass_handle, pass_writer = _open('pass')

                # Write to pass file
                pass_count += result.data_count
                if isinstance(result.results, Receptor):
                    pass_writer.writeReceptor(result.results)
                else:
                    for rec in result.results:  pass_writer.writeReceptor(rec)
            else:
                # Open fail file and define writer object
                if out_args['failed'] and fail_handle is None:
                    fail_handle, fail_writer = _open('fail')

                # Write to fail file
                fail_count += result.data_count
                if fail_writer is not None:
                    if isinstance(result.data, Receptor):
                        pass_writer.writeReceptor(result.data)
                    else:
                        for rec in result.data:  fail_writer.writeReceptor(rec)
        else:
            sys.stderr.write('PID %s:  Error in sibling process detected. Cleaning up.\n' \
                             % os.getpid())
            return None

        # Print total counts
        printProgress(rec_count, result_count, 0.05, start_time)

        # Update return values
        log = OrderedDict()
        log['OUTPUT'] = os.path.basename(pass_handle.name) if pass_handle is not None else None
        log['RECORDS'] = rec_count
        log['GROUPS'] = set_count
        log['PASS'] = pass_count
        log['FAIL'] = fail_count
        collect_dict = {'log':log, 'out_files': [pass_handle.name]}
        collect_queue.put(collect_dict)

        # Close file handles
        if pass_handle is not None:  pass_handle.close()
        if fail_handle is not None:  fail_handle.close()
        if log_handle is not None:  log_handle.close()
    except:
        alive.value = False
        raise

    return None