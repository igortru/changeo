#!/usr/bin/env python3
"""
Parses tab delimited database files
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from changeo import __version__, __date__

# Imports
import csv
import os
import re
from argparse import ArgumentParser
from collections import OrderedDict
from itertools import chain

from textwrap import dedent
from time import time
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Alphabet import IUPAC

# Presto and changeo imports
from presto.Defaults import default_delimiter, default_out_args
from presto.Annotation import flattenAnnotation
from presto.IO import getOutputHandle, printLog, printProgress, printMessage
from changeo.Defaults import default_csv_size
from changeo.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from changeo.IO import countDbFile, getDbFields
from changeo.Parsers import ChangeoReader, ChangeoWriter

# System settings
csv.field_size_limit(default_csv_size)

# Defaults
default_id_field = 'SEQUENCE_ID'
default_seq_field = 'SEQUENCE_IMGT'
default_germ_field = 'GERMLINE_IMGT_D_MASK'
default_index_field = 'INDEX'
default_db_xref = 'IMGT/GENE-DB'

# TODO:  convert SQL-ish operations to modify_func() as per ParseHeaders

def getDbSeqRecord(db_record, id_field, seq_field, meta_fields=None, 
                   delimiter=default_delimiter):
    """
    Parses a database record into a SeqRecord

    Arguments: 
    db_record = a dictionary containing a database record
    id_field = the field containing identifiers
    seq_field = the field containing sequences
    meta_fields = a list of fields to add to sequence annotations
    delimiter = a tuple of delimiters for (fields, values, value lists) 

    Returns: 
    a SeqRecord
    """
    # Return None if ID or sequence fields are empty
    if not db_record[id_field] or not db_record[seq_field]:
        return None
    
    # Create description string
    desc_dict = OrderedDict([('ID', db_record[id_field])])
    if meta_fields is not None:
        desc_dict.update([(f, db_record[f]) for f in meta_fields if f in db_record]) 
    desc_str = flattenAnnotation(desc_dict, delimiter=delimiter)
    
    # Create SeqRecord
    seq_record = SeqRecord(Seq(db_record[seq_field], IUPAC.ambiguous_dna),
                           id=desc_str, name=desc_str, description='')
        
    return seq_record


def splitDbFile(db_file, field, num_split=None, out_args=default_out_args):
    """
    Divides a tab-delimited database file into segments by description tags

    Arguments:
    db_file = filename of the tab-delimited database file to split
    field = the field name by which to split db_file
    num_split = the numerical threshold by which to group sequences;
                if None treat field as textual
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    a list of output file names
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'split'
    log['FILE'] = os.path.basename(db_file)
    log['FIELD'] = field
    log['NUM_SPLIT'] = num_split
    printLog(log)

    # Open reader
    db_handle = open(db_file, 'rt')
    reader = ChangeoReader(db_handle, receptor=False)
    out_fields = getDbFields(db_file)
    # Determine total numbers of records
    rec_count = countDbFile(db_file)

    start_time = time()
    count = 0
    # Sort records into files based on textual field
    if num_split is None:
        # Create set of unique field tags
        with open(db_file, 'rt') as tmp_handle:
            tmp_iter = ChangeoReader(tmp_handle, receptor=False)
            tag_list = list(set([row[field] for row in tmp_iter]))

        # Forbidden characters in filename and replacements
        no_good = {'\/':'f','\\':'b','?':'q','\%':'p','*':'s',':':'c',
                   '\|':'pi','\"':'dq','\'':'sq','<':'gt','>':'lt',' ':'_'}
        # Replace forbidden characters in tag_list
        tag_dict = {}
        for tag in tag_list:
            for c,r in no_good.items():
                tag_dict[tag] = (tag_dict.get(tag, tag).replace(c,r) \
                                 if c in tag else tag_dict.get(tag, tag))

        # Create output handles
        handles_dict = {tag: getOutputHandle(db_file,
                                             out_label='%s-%s' % (field, label),
                                             out_name=out_args['out_name'],
                                             out_dir=out_args['out_dir'],
                                             out_type='tsv')
                        for tag, label in tag_dict.items()}

        # Create Db writer instances
        writers_dict = {tag: ChangeoWriter(handles_dict[tag], fields=out_fields)
                        for tag in tag_dict}

        # Iterate over records
        for row in reader:
            printProgress(count, rec_count, 0.05, start_time)
            count += 1
            # Write row to appropriate file
            tag = row[field]
            writers_dict[tag].writeDict(row)

    # Sort records into files based on numeric num_split
    else:
        num_split = float(num_split)

        # Create output handles
        handles_dict = {'under': getOutputHandle(db_file,
                                                 out_label='under-%.1f' % num_split,
                                                 out_name=out_args['out_name'],
                                                 out_dir=out_args['out_dir'],
                                                 out_type='tsv'),
                        'atleast': getOutputHandle(db_file,
                                                   out_label='atleast-%.1f' % num_split,
                                                   out_name=out_args['out_name'],
                                                   out_dir=out_args['out_dir'],
                                                   out_type='tsv')}

        # Create Db writer instances
        writers_dict = {'under': ChangeoWriter(handles_dict['under'], fields=out_fields),
                        'atleast': ChangeoWriter(handles_dict['atleast'], fields=out_fields)}

        # Iterate over records
        for row in reader:
            printProgress(count, rec_count, 0.05, start_time)
            count += 1
            tag = row[field]
            tag = 'under' if float(tag) < num_split else 'atleast'
            writers_dict[tag].writeDict(row)

    # Write log
    printProgress(count, rec_count, 0.05, start_time)
    log = OrderedDict()
    for i, k in enumerate(handles_dict):
        log['OUTPUT%i' % (i + 1)] = os.path.basename(handles_dict[k].name)
    log['RECORDS'] = rec_count
    log['PARTS'] = len(handles_dict)
    log['END'] = 'ParseDb'
    printLog(log)

    # Close output file handles
    db_handle.close()
    for t in handles_dict: handles_dict[t].close()

    return [handles_dict[t].name for t in handles_dict]


# TODO:  SHOULD ALLOW FOR UNSORTED CLUSTER COLUMN
# TODO:  SHOULD ALLOW FOR GROUPING FIELDS
def convertDbBaseline(db_file, id_field=default_id_field, seq_field=default_seq_field,
                      germ_field=default_germ_field, cluster_field=None,
                      meta_fields=None, out_args=default_out_args):
    """
    Builds fasta files from database records

    Arguments: 
    db_file = the database file name
    id_field = the field containing identifiers
    seq_field = the field containing sample sequences
    germ_field = the field containing germline sequences
    cluster_field = the field containing clonal groupings
                    if None write the germline for each record
    meta_fields = a list of fields to add to sequence annotations
    out_args = common output argument dictionary from parseCommonArgs
                    
    Returns: 
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'fasta'
    log['FILE'] = os.path.basename(db_file)
    log['ID_FIELD'] = id_field
    log['SEQ_FIELD'] = seq_field
    log['GERM_FIELD'] = germ_field
    log['CLUSTER_FIELD'] = cluster_field
    if meta_fields is not None:  log['META_FIELDS'] = ','.join(meta_fields)
    printLog(log)
    
    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='sequences', out_dir=out_args['out_dir'], 
                                  out_name=out_args['out_name'], out_type='clip')
    # Count records
    result_count = countDbFile(db_file)
    
    # Iterate over records
    start_time = time()
    rec_count = germ_count = pass_count = fail_count = 0
    cluster_last = None
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1
        
        # Update cluster ID
        cluster = rec.get(cluster_field, None)
        
        # Get germline SeqRecord when needed
        if cluster_field is None:
            germ = getDbSeqRecord(rec, id_field, germ_field, meta_fields, 
                                  delimiter=out_args['delimiter'])
            germ.id = '>' + germ.id
        elif cluster != cluster_last:
            germ = getDbSeqRecord(rec, cluster_field, germ_field, 
                                  delimiter=out_args['delimiter'])
            germ.id = '>' + germ.id            
        else:
            germ = None

        # Get read SeqRecord
        seq = getDbSeqRecord(rec, id_field, seq_field, meta_fields, 
                             delimiter=out_args['delimiter'])
        
        # Write germline
        if germ is not None:
            germ_count += 1
            SeqIO.write(germ, pass_handle, 'fasta')
        
        # Write sequences
        if seq is not None:
            pass_count += 1
            SeqIO.write(seq, pass_handle, 'fasta')
        else:
            fail_count += 1
        
        # Set last cluster ID
        cluster_last = cluster
        
    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['GERMLINES'] = germ_count
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def convertDbFasta(db_file, id_field=default_id_field, seq_field=default_seq_field,
                 meta_fields=None, out_args=default_out_args):
    """
    Builds fasta files from database records

    Arguments: 
    db_file = the database file name
    id_field = the field containing identifiers
    seq_field = the field containing sequences
    meta_fields = a list of fields to add to sequence annotations
    out_args = common output argument dictionary from parseCommonArgs
                    
    Returns: 
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'fasta'
    log['FILE'] = os.path.basename(db_file)
    log['ID_FIELD'] = id_field
    log['SEQ_FIELD'] = seq_field
    if meta_fields is not None:  log['META_FIELDS'] = ','.join(meta_fields)
    printLog(log)
    
    # Open file handles
    out_type = 'fasta'
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='sequences', out_dir=out_args['out_dir'], 
                                  out_name=out_args['out_name'], out_type=out_type)
    # Count records
    result_count = countDbFile(db_file)
    
    # Iterate over records
    start_time = time()
    rec_count = pass_count = fail_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1

        # Get SeqRecord
        seq = getDbSeqRecord(rec, id_field, seq_field, meta_fields, out_args['delimiter'])

        # Write sequences
        if seq is not None:
            pass_count += 1
            SeqIO.write(seq, pass_handle, out_type)
        else:
            fail_count += 1
        
    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def addDbFile(db_file, fields, values, out_args=default_out_args):
    """
    Adds field and value pairs to a database file

    Arguments:
    db_file = the database file name
    fields = a list of fields to add
    values = a list of values to assign to all rows of each field
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'add'
    log['FILE'] = os.path.basename(db_file)
    log['FIELDS'] = ','.join(fields)
    log['VALUES'] = ','.join(values)
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-add', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file, add=fields)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)
    # Count records
    result_count = countDbFile(db_file)

    # Define fields and values to append
    add_dict = {k:v for k,v in zip(fields, values) if k not in db_iter.fields}

    # Iterate over records
    start_time = time()
    rec_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1
        # Write updated row
        rec.update(add_dict)
        pass_writer.writeDict(rec)

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def indexDbFile(db_file, field=default_index_field, out_args=default_out_args):
    """
    Adds an index column to a database file

    Arguments:
    db_file = the database file name
    field = the name of the index field to add
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'index'
    log['FILE'] = os.path.basename(db_file)
    log['FIELD'] = field
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-index', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file, add=field)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)
    # Count records
    result_count = countDbFile(db_file)

    # Iterate over records
    start_time = time()
    rec_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1

        # Add count and write updated row
        rec.update({field:rec_count})
        pass_writer.writeDict(rec)

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def dropDbFile(db_file, fields, out_args=default_out_args):
    """
    Deletes entire fields from a database file

    Arguments:
    db_file = the database file name
    fields = a list of fields to drop
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'add'
    log['FILE'] = os.path.basename(db_file)
    log['FIELDS'] = ','.join(fields)
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-drop', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file, exclude=fields)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)
    # Count records
    result_count = countDbFile(db_file)

    # Iterate over records
    start_time = time()
    rec_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1
        # Write row
        pass_writer.writeDict(rec)

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()

    return pass_handle.name


def deleteDbFile(db_file, fields, values, logic='any', regex=False,
                 out_args=default_out_args):
    """
    Deletes records from a database file

    Arguments: 
    db_file = the database file name
    fields = a list of fields to check for deletion criteria
    values = a list of values defining deletion targets
    logic = one of 'any' or 'all' defining whether one or all fields must have a match.
    regex = if False do exact full string matches; if True allow partial regex matches.
    out_args = common output argument dictionary from parseCommonArgs
                    
    Returns: 
    the output file name
    """
    # Define string match function
    if regex:
        def _match_func(x, patterns):  return any([re.search(p, x) for p in patterns])
    else:
        def _match_func(x, patterns):  return x in patterns

    # Define logic function
    if logic == 'any':
        _logic_func = any
    elif logic == 'all':
        _logic_func = all

    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'delete'
    log['FILE'] = os.path.basename(db_file)
    log['FIELDS'] = ','.join(fields)
    log['VALUES'] = ','.join(values)
    printLog(log)
    
    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-delete', out_dir=out_args['out_dir'], 
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)
    # Count records
    result_count = countDbFile(db_file)

    # Iterate over records
    start_time = time()
    rec_count = pass_count = fail_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1
        # Check for deletion values in all fields
        delete = _logic_func([_match_func(rec.get(f, False), values) for f in fields])
        
        # Write sequences
        if not delete:
            pass_count += 1
            pass_writer.writeDict(rec)
        else:
            fail_count += 1
        
    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['KEPT'] = pass_count
    log['DELETED'] = fail_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()
 
    return pass_handle.name


def renameDbFile(db_file, fields, names, out_args=default_out_args):
    """
    Renames fields in a database file

    Arguments:
    db_file = the database file name
    fields = a list of fields to rename
    values = a list of new names for fields
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'rename'
    log['FILE'] = os.path.basename(db_file)
    log['FIELDS'] = ','.join(fields)
    log['NAMES'] = ','.join(names)
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-rename', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')

    # Get header and rename fields
    header = getDbFields(db_file)
    for f, n in zip(fields, names):
        i = header.index(f)
        header[i] = n

    # Open writer
    pass_writer = ChangeoWriter(pass_handle, fields=header)

    # Count records
    result_count = countDbFile(db_file)

    # Iterate over records
    start_time = time()
    rec_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1
        # TODO:  repeating renaming is unnecessary.  should had a non-dict reader/writer to DbCore
        # Rename fields
        for f, n in zip(fields, names):
            rec[n] = rec.pop(f)
        # Write
        pass_writer.writeDict(rec)

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def selectDbFile(db_file, fields, values, logic='any', regex=False,
                 out_args=default_out_args):
    """
    Selects records from a database file

    Arguments:
    db_file = the database file name
    fields = a list of fields to check for selection criteria
    values = a list of values defining selection targets
    logic = one of 'any' or 'all' defining whether one or all fields must have a match.
    regex = if False do exact full string matches; if True allow partial regex matches.
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    # Define string match function
    if regex:
        def _match_func(x, patterns):  return any([re.search(p, x) for p in patterns])
    else:
        def _match_func(x, patterns):  return x in patterns

    # Define logic function
    if logic == 'any':
        _logic_func = any
    elif logic == 'all':
        _logic_func = all

    # Print console log
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'select'
    log['FILE'] = os.path.basename(db_file)
    log['FIELDS'] = ','.join(fields)
    log['VALUES'] = ','.join(values)
    log['REGEX'] =regex
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-select', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)
    # Count records
    result_count = countDbFile(db_file)

    # Iterate over records
    start_time = time()
    rec_count = pass_count = fail_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1

        # Check for selection values in all fields
        select = _logic_func([_match_func(rec.get(f, False), values) for f in fields])

        # Write sequences
        if select:
            pass_count += 1
            pass_writer.writeDict(rec)
        else:
            fail_count += 1

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['SELECTED'] = pass_count
    log['DISCARDED'] = fail_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def sortDbFile(db_file, field, numeric=False, descend=False,
               out_args=default_out_args):
    """
    Sorts records by values in an annotation field

    Arguments:
    db_file = the database filename
    field = the field name to sort by
    numeric = if True sort field numerically;
              if False sort field alphabetically
    descend = if True sort in descending order;
              if False sort in ascending order

    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'sort'
    log['FILE'] = os.path.basename(db_file)
    log['FIELD'] = field
    log['NUMERIC'] = numeric
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-sort', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)

    # Store all records in a dictionary
    start_time = time()
    printMessage("Indexing: Running", start_time=start_time)
    db_dict = {i:r for i, r in enumerate(db_iter)}
    result_count = len(db_dict)

    # Sort db_dict by field values
    tag_dict = {k:v[field] for k, v in db_dict.items()}
    if numeric:  tag_dict = {k:float(v or 0) for k, v in tag_dict.items()}
    sorted_keys = sorted(tag_dict, key=tag_dict.get, reverse=descend)
    printMessage("Indexing: Done", start_time=start_time, end=True)

    # Iterate over records
    start_time = time()
    rec_count = 0
    for key in sorted_keys:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1

        # Write records
        pass_writer.writeDict(db_dict[key])

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def updateDbFile(db_file, field, values, updates, out_args=default_out_args):
    """
    Updates field and value pairs to a database file

    Arguments:
    db_file = the database file name
    field = the field to update
    values = a list of values to specifying which rows to update
    updates = a list of values to update each value with
    out_args = common output argument dictionary from parseCommonArgs

    Returns:
    the output file name
    """
    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'update'
    log['FILE'] = os.path.basename(db_file)
    log['FIELD'] = field
    log['VALUES'] = ','.join(values)
    log['UPDATES'] = ','.join(updates)
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle, receptor=False)
    pass_handle = getOutputHandle(db_file, out_label='parse-update', out_dir=out_args['out_dir'],
                                  out_name=out_args['out_name'], out_type='tsv')
    out_fields = getDbFields(db_file)
    pass_writer = ChangeoWriter(pass_handle, fields=out_fields)
    # Count records
    result_count = countDbFile(db_file)

    # Iterate over records
    start_time = time()
    rec_count = pass_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1

        # Updated values if found
        for x, y in zip(values, updates):
            if rec[field] == x:
                rec[field] = y
                pass_count += 1

        # Write records
        pass_writer.writeDict(rec)

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['RECORDS'] = rec_count
    log['UPDATED'] = pass_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    pass_handle.close()
    db_handle.close()

    return pass_handle.name


def makeGenbankFeatures(record, inference=None, db_xref=default_db_xref, ungap=False):
    """
    Creates a feature table for GenBank submissions

    Arguments:
      record : Receptor record.
      inference : Reference alignment tool.
      db_xref : Reference database name.
      ungap : if True remove IMGT gaps from feature positions

    Returns:
      dict : dictionary defining GenBank features where the key is a tuple
             (start, end, feature key) and values are a list of
             tuples contain (qualifier key, qualifier value).
    """
    # Define return object
    result = OrderedDict()

    # Set inference type
    if inference is not None:
        inference = 'similar to DNA sequence:%s' % inference

    # Define position offset for removal of IMGT gaps
    gaps = str(record.sequence_imgt)[:312].count('.') if ungap else 0

    # Calculate variable, constant and junction boundaries
    v_end = record.v_germ_end_imgt - gaps - 1
    variable_end = v_end + \
                   record.np1_length + record.d_germ_length + record.np2_length + \
                   record.j_germ_length
    c_region_start = 1 + variable_end
    c_region_end = variable_end + len(record.sequence_input[(record.j_seq_end - 1):])
    junction_start = 310 - gaps

    # CDS
    #     codon_start (must indicate codon offset)
    codon_start = 1 + (junction_start - 1) % 3
    cds_start = '<%i' % 1 if record.v_germ_start_vdj > 1 else 1
    cds_end = '>%i' % c_region_end if c_region_start < c_region_end else '>%i' % variable_end
    cds = [('product', 'B cell receptor'),
           ('codon_start', codon_start)]
    result[(cds_start,
            cds_end,
            'CDS')] = cds

    # V_region
    variable_region = []
    result[(1, variable_end, 'V_region')] = variable_region

    # C_region
    #     gene
    #     db_xref
    #     inference
    if c_region_start < c_region_end:
        c_region = []
        result[(c_region_start, '>%i' % c_region_end, 'C_region')] = c_region

    # V_segment
    #     gene (gene name)
    #     allele (allele only, without gene name, don't use if ambiguous)
    #     db_xref (database link)
    #     inference (reference alignment tool)
    v_gene = record.getVGene()
    v_segment = [('gene', v_gene),
                 ('allele', record.getVAlleleNumber()),
                 ('db_xref', '%s:%s' % (db_xref, v_gene)),
                 ('inference', inference)]
    result[(1, v_end, 'V_segment')] = v_segment

    # D_segment
    #     gene
    #     allele
    #     db_xref
    #     inference
    d_gene = record.getDGene()
    if d_gene:
        # Define D and J start
        d_start = 1 + v_end + record.np1_length
        j_start = d_start + record.d_germ_length + record.np2_length

        # D feature
        d_segment = [('gene', d_gene),
                     ('allele', record.getDAlleleNumber()),
                     ('db_xref', '%s:%s' % (db_xref, d_gene)),
                     ('inference', inference)]
        result[(d_start,
                d_start + record.d_germ_length - 1,
                'D_segment')] = d_segment
    else:
        j_start = 1 + v_end + record.np1_length + record.np2_length

    # J_segment
    #     gene
    #     allele
    #     db_xref
    #     inference
    j_gene = record.getJGene()
    j_segment = [('gene', j_gene),
                 ('allele', record.getVAlleleNumber()),
                 ('db_xref', '%s:%s' % (db_xref, j_gene)),
                 ('inference', inference)]
    result[(j_start,
            j_start + record.j_germ_length - 1,
            'J_segment')] = j_segment

    # misc_feature  (1-based closed interval positions)
    #     function = junction
    #     inference
    junction = [('function', 'junction'),
                ('inference', inference)]
    result[(junction_start,
            junction_start + record.junction_length - 1,
            'misc_feature')] = junction

    return result

def makeGenbankSequence(record, organism=None, ungap=False):
    """
    Creates a sequence for GenBank submissions

    Arguments:
      record : Receptor record.
      organism : scientific name of the organism.
      ungap : if True remove IMGT gaps from feature positions

    Returns:
      SeqRecord : Object containing the output sequence
    """
    seq = ''.join([str(record.sequence_imgt),
                   str(record.sequence_input[(record.j_seq_end - 1):])])
    seq = seq.replace('-', 'N')

    # Deal with IMGT gaps
    if ungap:
        seq = seq.replace('.', '')
    else:
        seq = seq.replace('.', '-')

    seq_id = record.sequence_id.replace(' ', '_')
    if organism is not None:
        seq_id = '%s [organism=%s]' % (seq_id, organism)

    # Return SeqRecord
    return SeqRecord(Seq(seq, IUPAC.ambiguous_dna), id=seq_id,
                     name=seq_id, description='')


def convertDbGenbank(db_file, inference=None, db_xref=None, organism=None,
                     ungap=False, out_args=default_out_args):
    """
    Builds a GenBank submission tbl file from records

    Arguments:
      db_file : the database file name.
      inference : reference alignment tool.
      db_xref : reference database link.
      organism : scientific name of the organism.
      ungap : if True remove IMGT gaps from feature positions and output sequence.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      tuple : the output (feature table, fasta) file names.
    """
    # .tbl file format
    #   Line 1, Column 1: Start location of feature
    #   Line 1, Column 2: Stop location of feature
    #   Line 1, Column 3: Feature key
    #   Line 2, Column 4: Qualifier key
    #   Line 2, Column 5: Qualifier value
    #
    # Example .tbl format
    # >Feature Sc_16
    # 1     7000    REFERENCE
    #                       PubMed          8849441
    # <1    1050    gene
    #                       gene            ATH1
    # <1    1009    CDS
    #                       product         acid trehalase
    #                       product         Ath1p
    #                       codon_start     2
    #
    # Required feature keys:
    #   CDS
    #       codon_start (must indicate codon offset)
    #   V_region
    #   V_segment
    #       gene (gene name)
    #       allele (allele only, without gene name, don't use if ambiguous)
    #       db_xref (database link)
    #       inference (reference alignment tool)
    #   D_segment
    #       gene
    #       allele
    #       db_xref
    #       inference
    #   J_segment
    #       gene
    #       allele
    #       db_xref
    #       inference
    #   C_region
    #       gene
    #       db_xref
    #       inference
    #   misc_feature  (1-based closed interval positions)
    #       function = JUNCTION
    #       inference
    #
    # Changeo fields required
    # SEQUENCE_ID
    # SEQUENCE_VDJ
    # V_CALL
    # D_CALL
    # J_CALL
    # V_SEQ_START
    # V_SEQ_LENGTH
    # D_SEQ_START
    # D_SEQ_LENGTH
    # J_SEQ_START
    # J_SEQ_LENGTH
    # JUNCTION
    # JUNCTION_START (need to add)
    # JUNCTION_LENGTH
    # TRANSLATION_START (maybe from V_GERM_START_IMGT?)

    log = OrderedDict()
    log['START'] = 'ParseDb'
    log['COMMAND'] = 'genbank'
    log['FILE'] = os.path.basename(db_file)
    printLog(log)

    # Open file handles
    db_handle = open(db_file, 'rt')
    db_iter = ChangeoReader(db_handle)
    tbl_handle = getOutputHandle(db_file, out_label='genbank', out_dir=out_args['out_dir'],
                                 out_name=out_args['out_name'], out_type='tbl')
    fsa_handle = getOutputHandle(db_file, out_label='genbank', out_dir=out_args['out_dir'],
                                 out_name=out_args['out_name'], out_type='fsa')

    # Count records
    result_count = countDbFile(db_file)

    # Define writer
    writer = csv.writer(tbl_handle, delimiter='\t', quoting=csv.QUOTE_NONE)

    # Iterate over records
    start_time = time()
    rec_count = 0
    for rec in db_iter:
        # Print progress for previous iteration
        printProgress(rec_count, result_count, 0.05, start_time)
        rec_count += 1

        # Extract table dictionary
        tbl = makeGenbankFeatures(rec, db_xref=db_xref, inference=inference, ungap=ungap)
        seq = makeGenbankSequence(rec, organism=organism, ungap=ungap)

        # Write table
        tbl_id = rec.sequence_id.replace(' ', '_')
        writer.writerow(['>Features', tbl_id])
        for feature, qualifiers in tbl.items():
            writer.writerow(feature)
            if qualifiers:
                for x in qualifiers:
                    writer.writerow(list(chain(['', '', ''], x)))

        # Write sequence
        SeqIO.write(seq, fsa_handle, 'fasta')

    # Print counts
    printProgress(rec_count, result_count, 0.05, start_time)
    log = OrderedDict()
    log['OUTPUT_TBL'] = os.path.basename(tbl_handle.name)
    log['OUTPUT_FSA'] = os.path.basename(fsa_handle.name)
    log['RECORDS'] = rec_count
    log['END'] = 'ParseDb'
    printLog(log)

    # Close file handles
    tbl_handle.close()
    fsa_handle.close()
    db_handle.close()

    return (tbl_handle.name, fsa_handle.name)


def getArgParser():
    """
    Defines the ArgumentParser

    Arguments: 
    None
                      
    Returns: 
    an ArgumentParser object
    """
    # Define input and output field help message
    fields = dedent(
             '''
             output files:
                 sequences
                     FASTA formatted sequences output from the subcommands fasta and clip.
                 <field>-<value>
                     database files partitioned by annotation <field> and <value>.
                 parse-<command>
                     output of the database modification functions where <command> is one of
                     the subcommands add, index, drop, delete, rename, select, sort or update.

             required fields:
                 SEQUENCE_ID
                 
             optional fields:
                 JUNCTION, SEQUENCE_IMGT, SEQUENCE_VDJ, GERMLINE_IMGT, GERMLINE_VDJ,
                 GERMLINE_IMGT_D_MASK, GERMLINE_VDJ_D_MASK,
                 GERMLINE_IMGT_V_REGION, GERMLINE_VDJ_V_REGION
                
             output fields:
                 None
             ''')
    
    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter)
    parser.add_argument('--version', action='version',
                        version='%(prog)s:' + ' %s-%s' %(__version__, __date__))
    subparsers = parser.add_subparsers(title='subcommands', dest='command', metavar='',
                                       help='Database operation')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Define parent parser
    parser_parent = getCommonArgParser(seq_in=False, seq_out=False, db_in=True,
                                       failed=False, log=False)

    # Subparser to convert database entries to sequence file
    parser_seq = subparsers.add_parser('fasta', parents=[parser_parent],
                                       formatter_class=CommonHelpFormatter,
                                       help='Creates a fasta file from database records.',
                                       description='Creates a fasta file from database records.')
    parser_seq.add_argument('--if', action='store', dest='id_field', 
                            default=default_id_field,
                            help='The name of the field containing identifiers')
    parser_seq.add_argument('--sf', action='store', dest='seq_field', 
                            default=default_seq_field,
                            help='The name of the field containing sequences')
    parser_seq.add_argument('--mf', nargs='+', action='store', dest='meta_fields',
                            help='List of annotation fields to add to the sequence description')
    parser_seq.set_defaults(func=convertDbFasta)
    
    # Subparser to convert database entries to clip-fasta file
    parser_baseln = subparsers.add_parser('baseline', parents=[parser_parent],
                                          formatter_class=CommonHelpFormatter,
                                          description='Creates a BASELINe fasta file from database records.',
                                          help='''Creates a specially formatted fasta file
                                               from database records for input into the BASELINe
                                               website. The format groups clonally related sequences
                                               sequentially, with the germline sequence preceding
                                               each clone and denoted by headers starting with ">>".''')
    parser_baseln.add_argument('--if', action='store', dest='id_field',
                               default=default_id_field,
                               help='The name of the field containing identifiers')
    parser_baseln.add_argument('--sf', action='store', dest='seq_field',
                               default=default_seq_field,
                               help='The name of the field containing reads')
    parser_baseln.add_argument('--gf', action='store', dest='germ_field',
                               default=default_germ_field,
                               help='The name of the field containing germline sequences')
    parser_baseln.add_argument('--cf', action='store', dest='cluster_field', default=None,
                               help='The name of the field containing containing sorted clone IDs')
    parser_baseln.add_argument('--mf', nargs='+', action='store', dest='meta_fields',
                               help='List of annotation fields to add to the sequence description')
    parser_baseln.set_defaults(func=convertDbBaseline)

    # Subparser to partition files by annotation values
    parser_split = subparsers.add_parser('split', parents=[parser_parent],
                                         formatter_class=CommonHelpFormatter,
                                         help='Splits database files by field values.',
                                         description='Splits database files by field values')
    parser_split.add_argument('-f', action='store', dest='field', type=str, required=True,
                              help='Annotation field by which to split database files.')
    parser_split.add_argument('--num', action='store', dest='num_split', type=float, default=None,
                              help='''Specify to define the field as numeric and group
                                   records by whether they are less than or at least
                                   (greater than or equal to) the specified value.''')
    parser_split.set_defaults(func=splitDbFile)

    # Subparser to add records
    parser_add = subparsers.add_parser('add', parents=[parser_parent],
                                       formatter_class=CommonHelpFormatter,
                                       help='Adds field and value pairs.',
                                       description='Adds field and value pairs.')
    parser_add.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                               help='The name of the fields to add.')
    parser_add.add_argument('-u', nargs='+', action='store', dest='values', required=True,
                               help='The value to assign to all rows for each field.')
    parser_add.set_defaults(func=addDbFile)

    # Subparser to delete records
    parser_delete = subparsers.add_parser('delete', parents=[parser_parent], 
                                          formatter_class=CommonHelpFormatter,
                                          help='Deletes specific records.',
                                          description='Deletes specific records.')
    parser_delete.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                               help='The name of the fields to check for deletion criteria.')
    parser_delete.add_argument('-u', nargs='+', action='store', dest='values', default=['', 'NA'],
                               help='''The values defining which records to delete. A value
                                    may appear in any of the fields specified with -f.''')
    parser_delete.add_argument('--logic', action='store', dest='logic',
                               choices=('any', 'all'), default='any',
                               help='''Defines whether a value may appear in any field (any)
                                    or whether it must appear in all fields (all).''')
    parser_delete.add_argument('--regex', action='store_true', dest='regex',
                               help='''If specified, treat values as regular expressions
                                    and allow partial string matches.''')
    parser_delete.set_defaults(func=deleteDbFile)

    # Subparser to drop fields
    parser_drop = subparsers.add_parser('drop', parents=[parser_parent],
                                        formatter_class=CommonHelpFormatter,
                                        help='Deletes entire fields.',
                                        description='Deletes entire fields.')
    parser_drop.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                               help='The name of the fields to delete from the database.')
    parser_drop.set_defaults(func=dropDbFile)

    # Subparser to index fields
    parser_index = subparsers.add_parser('index', parents=[parser_parent],
                                         formatter_class=CommonHelpFormatter,
                                         help='Adds a numeric index field.',
                                         description='Adds a numeric index field.')
    parser_index.add_argument('-f', action='store', dest='field',
                              default=default_index_field,
                              help='The name of the index field to add to the database.')
    parser_index.set_defaults(func=indexDbFile)

    # Subparser to rename fields
    parser_rename = subparsers.add_parser('rename', parents=[parser_parent],
                                          formatter_class=CommonHelpFormatter,
                                          help='Renames fields.',
                                          description='Renames fields.')
    parser_rename.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                               help='List of fields to rename.')
    parser_rename.add_argument('-k', nargs='+', action='store', dest='names', required=True,
                               help='List of new names for each field.')
    parser_rename.set_defaults(func=renameDbFile)

    # Subparser to select records
    parser_select = subparsers.add_parser('select', parents=[parser_parent],
                                          formatter_class=CommonHelpFormatter,
                                          help='Selects specific records.',
                                          description='Selects specific records.')
    parser_select.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                               help='The name of the fields to check for selection criteria.')
    parser_select.add_argument('-u', nargs='+', action='store', dest='values', required=True,
                               help='''The values defining with records to select. A value
                                    may appear in any of the fields specified with -f.''')
    parser_select.add_argument('--logic', action='store', dest='logic',
                               choices=('any', 'all'), default='any',
                               help='''Defines whether a value may appear in any field (any)
                                    or whether it must appear in all fields (all).''')
    parser_select.add_argument('--regex', action='store_true', dest='regex',
                               help='''If specified, treat values as regular expressions
                                    and allow partial string matches.''')
    parser_select.set_defaults(func=selectDbFile)

    # Subparser to sort file by records
    parser_sort = subparsers.add_parser('sort', parents=[parser_parent],
                                        formatter_class=CommonHelpFormatter,
                                        help='Sorts records by field values.',
                                        description='Sorts records by field values.')
    parser_sort.add_argument('-f', action='store', dest='field', type=str, required=True,
                             help='The annotation field by which to sort records.')
    parser_sort.add_argument('--num', action='store_true', dest='numeric', default=False,
                             help='''Specify to define the sort column as numeric rather
                                  than textual.''')
    parser_sort.add_argument('--descend', action='store_true', dest='descend',
                             help='''If specified, sort records in descending, rather
                             than ascending, order by values in the target field.''')
    parser_sort.set_defaults(func=sortDbFile)

    # Subparser to update records
    parser_update = subparsers.add_parser('update', parents=[parser_parent],
                                          formatter_class=CommonHelpFormatter,
                                          help='Updates field and value pairs.',
                                          description='Updates field and value pairs.')
    parser_update.add_argument('-f', action='store', dest='field', required=True,
                               help='The name of the field to update.')
    parser_update.add_argument('-u', nargs='+', action='store', dest='values', required=True,
                               help='The values that will be replaced.')
    parser_update.add_argument('-t', nargs='+', action='store', dest='updates', required=True,
                               help='''The new value to assign to each selected row.''')
    parser_update.set_defaults(func=updateDbFile)

    # Subparser to convert database entries to a GenBank tbl file
    parser_gb = subparsers.add_parser('genbank', parents=[parser_parent],
                                       formatter_class=CommonHelpFormatter,
                                       help='Creates a fasta and feature table file for GenBank submissions.',
                                       description='Creates a fasta and feature table file for GenBank submissions.')
    parser_gb.add_argument('--organism', action='store', dest='organism', default=None,
                            help='The scientific name of the organism.')
    parser_gb.add_argument('--inf', action='store', dest='inference', default=None,
                            help='Name and version of the inference tool used for reference alignment.')
    parser_gb.add_argument('--db', action='store', dest='db_xref', default=default_db_xref,
                            help='Link to the reference database used for alignment.')
    parser_gb.add_argument('--ungap', action='store_true', dest='ungap',
                            help='''If specified, remove IMGT gaps, denoted by dots, from the feature 
                                 positions and output sequence. By default, IMGT gaps will be retained and
                                 converted to dashes.''')
    parser_gb.set_defaults(func=convertDbGenbank)

    return parser


if __name__ == '__main__':
    """
    Parses command line arguments and calls main function
    """
    # Parse arguments
    parser = getArgParser()
    checkArgs(parser)
    args = parser.parse_args()
    args_dict = parseCommonArgs(args)
    # Convert case of fields
    if 'id_field' in args_dict:
        args_dict['id_field'] = args_dict['id_field'].upper()
    if 'seq_field' in args_dict:
        args_dict['seq_field'] = args_dict['seq_field'].upper()
    if 'germ_field' in args_dict:
        args_dict['germ_field'] = args_dict['germ_field'].upper()
    if 'field' in args_dict:
        args_dict['field'] = args_dict['field'].upper()
    if 'cluster_field' in args_dict and args_dict['cluster_field'] is not None:
        args_dict['cluster_field'] = args_dict['cluster_field'].upper()
    if 'meta_fields' in args_dict and args_dict['meta_fields'] is not None:
        args_dict['meta_fields'] = [f.upper() for f in args_dict['meta_fields']]
    if 'fields' in args_dict:
        args_dict['fields'] = [f.upper() for f in args_dict['fields']]

    # Check modify_args arguments
    if args.command == 'add' and len(args_dict['fields']) != len(args_dict['values']):
        parser.error('You must specify exactly one value (-u) per field (-f)')
    elif args.command == 'rename' and len(args_dict['fields']) != len(args_dict['names']):
        parser.error('You must specify exactly one new name (-k) per field (-f)')
    elif args.command == 'update' and len(args_dict['values']) != len(args_dict['updates']):
        parser.error('You must specify exactly one value (-u) per replacement (-t)')

    # Call parser function for each database file
    del args_dict['command']
    del args_dict['func']
    del args_dict['db_files']
    for f in args.__dict__['db_files']:
        args_dict['db_file'] = f
        args.func(**args_dict)
 
