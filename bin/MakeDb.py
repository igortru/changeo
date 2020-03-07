#!/usr/bin/env python3
"""
Create tab-delimited database file to store sequence alignment information
"""

# Info
__author__ = 'Namita Gupta, Jason Anthony Vander Heiden'
from changeo import __version__, __date__

# Imports
import os
import re
import csv
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent
from time import time
from Bio import SeqIO

# Presto and changeo imports
from presto.Annotation import parseAnnotation
from presto.IO import countSeqFile, printLog, printMessage, printProgress, printError, printWarning, readSeqFile
from changeo.Defaults import default_format, default_out_args
from changeo.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from changeo.Gene import buildGermline
from changeo.IO import countDbFile, extractIMGT, readGermlines, getFormatOperators, getOutputHandle, \
                       AIRRWriter, ChangeoWriter, IgBLASTReader, IgBLASTReaderAA, IMGTReader, IHMMuneReader
from changeo.Receptor import ChangeoSchema, AIRRSchema

# 10X Receptor attributes
cellranger_base = ['cell', 'c_call', 'conscount', 'umicount']
cellranger_extended = ['cell', 'c_call', 'conscount', 'umicount',
                       'v_call_10x', 'd_call_10x', 'j_call_10x',
                       'junction_10x', 'junction_10x_aa']


def readCellRanger(cellranger_file, fields=cellranger_base):
    """
    Load a Cell Ranger annotation table

    Arguments:
      cellranger_file (str): path to the annotation file.
      fields (list): list of fields to keep.

    Returns:
      dict: dict of dicts with contig_id as the primary key.
    """
    # Mapping of 10X annotations to Receptor attributes
    cellranger_map = {'cell':  'barcode',
                      'c_call': 'c_gene',
                      'locus': 'chain',
                      'conscount': 'reads',
                      'umicount': 'umis',
                      'v_call_10x': 'v_gene',
                      'd_call_10x': 'd_gene',
                      'j_call_10x': 'j_gene',
                      'junction_10x': 'cdr3_nt',
                      'junction_10x_aa': 'cdr3'}

    # Function to parse individual fields
    def _parse(x):
        return '' if x == 'None' else x

    # Generate annotation dictionary
    ann_dict = {}
    with open(cellranger_file) as csv_file:
        # Detect delimiters
        dialect = csv.Sniffer().sniff(csv_file.readline())
        csv_file.seek(0)
        # Read in annotation file
        csv_reader = csv.DictReader(csv_file, dialect=dialect)

        # Generate annotation dictionary
        for row in csv_reader:
            ann_dict[row['contig_id']] = {f: _parse(row[cellranger_map[f]]) for f in fields}

    return ann_dict


def addGermline(receptor, references):
    """
    Add full length germline to Receptor object

    Arguments:
      receptor (changeo.Receptor.Receptor): Receptor object to modify.
      references (dict): dictionary of IMGT-gapped references sequences.

    Returns:
      changeo.Receptor.Receptor: modified Receptor with the germline_imgt attribute added.
    """
    __, germlines, __ = buildGermline(receptor, references)
    germline_seq = None if germlines is None else germlines['full']
    receptor.setField('germline_imgt', germline_seq)

    return receptor


def getIDforIMGT(seq_file):
    """
    Create a sequence ID translation using IMGT truncation.

    Arguments:
      seq_file : a fasta file of sequences input to IMGT.

    Returns:
      dict : a dictionary of with the IMGT truncated ID as the key and the full sequence description as the value.
    """

    # Create a sequence ID translation using IDs truncate up to space or 50 chars
    ids = {}
    for rec in readSeqFile(seq_file):
        if len(rec.description) <= 50:
            id_key = rec.description
        else:
            id_key = re.sub('\||\s|!|&|\*|<|>|\?', '_', rec.description[:50])
        ids.update({id_key: rec.description})

    return ids


def getSeqDict(seq_file):
    """
    Create a dictionary from a sequence file.

    Arguments:
      seq_file : sequence file.

    Returns:
        dict : sequence description as keys with Bio.SeqRecords as values.
    """
    seq_dict = SeqIO.to_dict(readSeqFile(seq_file), key_function=lambda x: x.description)

    return seq_dict


def writeDb(records, fields, aligner_file, total_count, id_dict=None, annotations=None,
            partial=False, asis_id=True, writer=ChangeoWriter, out_file=None, out_args=default_out_args):
    """
    Writes parsed records to an output file
    
    Arguments: 
      records : a iterator of Receptor objects containing alignment data.
      fields : a list of ordered field names to write.
      aligner_file : input file name.
      total_count : number of records (for progress bar).
      id_dict : a dictionary of the truncated sequence ID mapped to the full sequence ID.
      annotations : additional annotation dictionary.
      partial : if True put incomplete alignments in the pass file.
      asis_id : if ID is to be parsed for pRESTO output with default delimiters.
      writer : writer class.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      None
    """
    # Wrapper for opening handles and writers
    def _open(x, f, writer=writer, out_file=out_file):
        if out_file is not None and x == 'pass':
            handle = open(out_file, 'w')
        else:
            handle = getOutputHandle(aligner_file,
                                     out_label='db-%s' % x,
                                     out_dir=out_args['out_dir'],
                                     out_name=out_args['out_name'],
                                     out_type=out_args['out_type'])
        return handle, writer(handle, fields=f)

    # Function to convert fasta header annotations to changeo columns
    def _changeo(f, header):
        h = [ChangeoSchema.fromReceptor(x) for x in header if x.upper() not in f]
        f.extend(h)
        return f

    def _airr(f, header):
        h = [AIRRSchema.fromReceptor(x) for x in header if x.lower() not in f]
        f.extend(h)
        return f

    # Function to verify IMGT-gapped sequence and junction concur
    def _imgt_check(rec):
        try:  check = (rec.junction == rec.sequence_imgt[309:(309 + rec.junction_length)])
        except TypeError:  check = False
        return check

    # Function to check for valid records strictly
    def _strict(rec):
        valid = [rec.v_call and rec.v_call != 'None',
                 rec.j_call and rec.j_call != 'None',
                 rec.functional is not None,
                 rec.sequence_imgt,
                 rec.junction,
                 _imgt_check(rec)]
        return all(valid)

    # Function to check for valid records loosely
    def _gentle(rec):
        valid = [rec.v_call and rec.v_call != 'None',
                 rec.d_call and rec.d_call != 'None',
                 rec.j_call and rec.j_call != 'None']
        return any(valid)

    # Set writer class and annotation conversion function
    if writer == ChangeoWriter:
        _annotate = _changeo
    elif writer == AIRRWriter:
        _annotate = _airr
    else:
        printError('Invalid output writer.')

    # Additional annotation (e.g. 10X cell calls)
    # _append_table = None
    # if cellranger_file is not None:
    #     with open(cellranger_file) as csv_file:
    #         # Read in annotation file (use Sniffer to discover file delimiters)
    #         dialect = csv.Sniffer().sniff(csv_file.readline())
    #         csv_file.seek(0)
    #         csv_reader = csv.DictReader(csv_file, dialect = dialect)
    #
    #         # Generate annotation dictionary
    #         anntab_dict = {entry['contig_id']: {cellranger_map[field]: entry[field] \
    #                        for field in cellranger_map.keys()} for entry in csv_reader}
    #
    #     fields = _annotate(fields, cellranger_map.values())
    #     _append_table = lambda sequence_id: anntab_dict[sequence_id]

    # Set pass criteria
    _pass = _gentle if partial else _strict

    # Define log handle
    if out_args['log_file'] is None:
        log_handle = None
    else:
        log_handle = open(out_args['log_file'], 'w')

    # Initialize handles, writers and counters
    pass_handle, pass_writer = None, None
    fail_handle, fail_writer = None, None
    pass_count, fail_count = 0, 0
    start_time = time()

    # Validate and write output
    printProgress(0, total_count, 0.05, start_time=start_time)
    for i, record in enumerate(records, start=1):
        # Replace sequence description with full string, if required
        if id_dict is not None and record.sequence_id in id_dict:
            record.sequence_id = id_dict[record.sequence_id]

        # Parse sequence description into new columns
        if not asis_id:
            try:
                ann_raw = parseAnnotation(record.sequence_id)
                record.sequence_id = ann_raw.pop('ID')

                # Convert to Receptor fields
                ann_parsed = OrderedDict()
                for k, v in ann_raw.items():
                    ann_parsed[ChangeoSchema.toReceptor(k)] = v

                # Add annotations to Receptor and update field list
                record.setDict(ann_parsed, parse=True)
                if i == 1:  fields = _annotate(fields, ann_parsed.keys())
            except IndexError:
                # Could not parse pRESTO-style annotations so fall back to no parse
                asis_id = True
                printWarning('Sequence annotation format not recognized. Sequence headers will not be parsed.')

        # Add supplemental annotation fields
        # if _append_table is not None:
        #     record.setDict(_append_table(record.sequence_id), parse=True)
        if annotations is not None:
            record.setDict(annotations[record.sequence_id], parse=True)
            if i == 1:  fields = _annotate(fields, annotations[record.sequence_id].keys())

        # Count pass or fail and write to appropriate file
        if _pass(record):
            pass_count += 1
            # Write row to pass file
            try:
                pass_writer.writeReceptor(record)
            except AttributeError:
                # Open pass file and writer
                pass_handle, pass_writer = _open('pass', fields)
                pass_writer.writeReceptor(record)
        else:
            fail_count += 1
            # Write row to fail file if specified
            if out_args['failed']:
                try:
                    fail_writer.writeReceptor(record)
                except AttributeError:
                    # Open fail file and writer
                    fail_handle, fail_writer = _open('fail', fields)
                    fail_writer.writeReceptor(record)

        # Write log
        if log_handle is not None:
            log = OrderedDict([('ID', record.sequence_id),
                               ('V_CALL', record.v_call),
                               ('D_CALL', record.d_call),
                               ('J_CALL', record.j_call),
                               ('FUNCTIONAL', record.functional),
                               ('IMGT_PASS', _imgt_check(record))])
            printLog(log, log_handle)

        # Print progress
        printProgress(i, total_count, 0.05, start_time=start_time)

    # Print console log
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name) if pass_handle is not None else None
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'MakeDb'
    printLog(log)

    # Close file handles
    output = {'pass': None, 'fail': None}
    if pass_handle is not None:
        output['pass'] = pass_handle.name
        pass_handle.close()
    if fail_handle is not None:
        output['fail'] = fail_handle.name
        fail_handle.close()

    return output


def parseIMGT(aligner_file, seq_file=None, repo=None, cellranger_file=None, partial=False, asis_id=True,
              extended=False, format=default_format, out_file=None, out_args=default_out_args):
    """
    Main for IMGT aligned sample sequences.

    Arguments:
      aligner_file : zipped file or unzipped folder output by IMGT.
      seq_file : FASTA file input to IMGT (from which to get seqID).
      repo : folder with germline repertoire files.
      partial : If True put incomplete alignments in the pass file.
      asis_id : if ID is to be parsed for pRESTO output with default delimiters.
      extended : if True add alignment score, FWR, CDR and junction fields to output file.
      format : output format. one of 'changeo' or 'airr'.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      dict : names of the 'pass' and 'fail' output files.
    """
    # Print parameter info
    log = OrderedDict()
    log['START'] = 'MakeDb'
    log['COMMAND'] = 'imgt'
    log['ALIGNER_FILE'] = aligner_file
    log['SEQ_FILE'] = os.path.basename(seq_file) if seq_file else ''
    log['ASIS_ID'] = asis_id
    log['PARTIAL'] = partial
    log['EXTENDED'] = extended
    printLog(log)

    start_time = time()
    printMessage('Loading files', start_time=start_time, width=20)

    # Extract IMGT files
    temp_dir, imgt_files = extractIMGT(aligner_file)

    # Count records in IMGT files
    total_count = countDbFile(imgt_files['summary'])

    # Get (parsed) IDs from fasta file submitted to IMGT
    id_dict = getIDforIMGT(seq_file) if seq_file else {}

    # Load supplementary annotation table
    if cellranger_file is not None:
        f = cellranger_extended if extended else cellranger_base
        annotations = readCellRanger(cellranger_file, fields=f)
    else:
        annotations = None

    printMessage('Done', start_time=start_time, end=True, width=20)

    # Define format operators
    try:
        __, writer, schema = getFormatOperators(format)
    except ValueError:
        printError('Invalid format %s.' % format)
    out_args['out_type'] = schema.out_type

    # Define output fields
    fields = list(schema.required)
    if extended:
        custom = IMGTReader.customFields(scores=True, regions=True, junction=True, schema=schema)
        fields.extend(custom)

    # Parse IMGT output and write db
    with open(imgt_files['summary'], 'r') as summary_handle, \
            open(imgt_files['gapped'], 'r') as gapped_handle, \
            open(imgt_files['ntseq'], 'r') as ntseq_handle, \
            open(imgt_files['junction'], 'r') as junction_handle:

        # Open parser
        parse_iter = IMGTReader(summary_handle, gapped_handle, ntseq_handle, junction_handle)

        # Add germline sequence
        if repo is None:
            germ_iter = parse_iter
        else:
            references = readGermlines(repo)
            # Check for IMGT-gaps in germlines
            if all('...' not in x for x in references.values()):
                printWarning('Germline reference sequences do not appear to contain IMGT-numbering spacers. Results may be incorrect.')
            germ_iter = (addGermline(x, references) for x in parse_iter)

        # Write db
        output = writeDb(germ_iter, fields=fields, aligner_file=aligner_file, total_count=total_count, 
                         annotations=annotations, id_dict=id_dict, asis_id=asis_id, partial=partial,
                         writer=writer, out_file=out_file, out_args=out_args)

    # Cleanup temp directory
    temp_dir.cleanup()

    return output


def parseIgBLAST(aligner_file, seq_file, repo, amino_acid=False, cellranger_file=None, partial=False,
                 asis_id=True, asis_calls=False, extended=False,
                 format='changeo', out_file=None, out_args=default_out_args):
    """
    Main for IgBLAST aligned sample sequences.

    Arguments:
      aligner_file : IgBLAST output file to process.
      seq_file : fasta file input to IgBlast (from which to get sequence).
      repo : folder with germline repertoire files.
      partial : If True put incomplete alignments in the pass file.
      asis_id : if ID is to be parsed for pRESTO output with default delimiters.
      asis_calls : if True do not parse gene calls for allele names.
      extended : if True add alignment scores, FWR, IMGT CDR, and IgBLAST CDR3 to the output.
      amino_acid : if True then the IgBLAST output files are results from igblastp. igblastn is assumed if False.
      format : output format. one of 'changeo' or 'airr'.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      dict : names of the 'pass' and 'fail' output files.
    """
    # Print parameter info
    log = OrderedDict()
    log['START'] = 'MakeDB'
    log['COMMAND'] = 'igblast-aa' if amino_acid else 'igblast'
    log['ALIGNER_FILE'] = os.path.basename(aligner_file)
    log['SEQ_FILE'] = os.path.basename(seq_file)
    log['ASIS_ID'] = asis_id
    log['ASIS_CALLS'] = asis_calls
    log['PARTIAL'] = partial
    log['EXTENDED'] = extended
    printLog(log)

    # Set amino acid conditions
    if amino_acid:
        format = '%s-aa' % format
        parser = IgBLASTReaderAA
    else:
        parser = IgBLASTReader

    # Start
    start_time = time()
    printMessage('Loading files', start_time=start_time, width=20)

    # Count records in sequence file
    total_count = countSeqFile(seq_file)

    # Get input sequence dictionary
    seq_dict = getSeqDict(seq_file)

    # Create germline repo dictionary
    references = readGermlines(repo, asis=asis_calls)

    # Load supplementary annotation table
    if cellranger_file is not None:
        f = cellranger_extended if extended else cellranger_base
        annotations = readCellRanger(cellranger_file, fields=f)
    else:
        annotations = None

    printMessage('Done', start_time=start_time, end=True, width=20)

    # Check for IMGT-gaps in germlines
    if all('...' not in x for x in references.values()):
        printWarning('Germline reference sequences do not appear to contain IMGT-numbering spacers. Results may be incorrect.')

    # Define format operators
    try:
        __, writer, schema = getFormatOperators(format)
    except ValueError:
        printError('Invalid format %s.' % format)
    out_args['out_type'] = schema.out_type

    # Define output fields
    fields = list(schema.required)
    if extended:
        custom = parser.customFields(scores=True, regions=True, cdr3=False, schema=schema)
        fields.extend(custom)

    # Parse and write output
    with open(aligner_file, 'r') as f:
        parse_iter = parser(f, seq_dict, references, asis_calls=asis_calls)
        germ_iter = (addGermline(x, references) for x in parse_iter)
        output = writeDb(germ_iter, fields=fields, aligner_file=aligner_file, total_count=total_count, 
                        annotations=annotations, partial=partial, asis_id=asis_id,
                        writer=writer, out_file=out_file, out_args=out_args)

    return output


def parseIHMM(aligner_file, seq_file, repo, cellranger_file=None, partial=False, asis_id=True,
              extended=False, format=default_format, out_file=None, out_args=default_out_args):
    """
    Main for iHMMuneAlign aligned sample sequences.

    Arguments:
      aligner_file : iHMMune-Align output file to process.
      seq_file : fasta file input to iHMMuneAlign (from which to get sequence).
      repo : folder with germline repertoire files.
      partial : If True put incomplete alignments in the pass file.
      asis_id : if ID is to be parsed for pRESTO output with default delimiters.
      extended : if True parse alignment scores, FWR and CDR region fields.
      format : output format. One of 'changeo' or 'airr'.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      dict : names of the 'pass' and 'fail' output files.
    """
    # Print parameter info
    log = OrderedDict()
    log['START'] = 'MakeDB'
    log['COMMAND'] = 'ihmm'
    log['ALIGNER_FILE'] = os.path.basename(aligner_file)
    log['SEQ_FILE'] = os.path.basename(seq_file)
    log['ASIS_ID'] = asis_id
    log['PARTIAL'] = partial
    log['EXTENDED'] = extended
    printLog(log)

    start_time = time()
    printMessage('Loading files', start_time=start_time, width=20)

    # Count records in sequence file
    total_count = countSeqFile(seq_file)

    # Get input sequence dictionary
    seq_dict = getSeqDict(seq_file)

    # Create germline repo dictionary
    references = readGermlines(repo)

    # Load supplementary annotation table
    if cellranger_file is not None:
        f = cellranger_extended if extended else cellranger_base
        annotations = readCellRanger(cellranger_file, fields=f)
    else:
        annotations = None

    printMessage('Done', start_time=start_time, end=True, width=20)

    # Check for IMGT-gaps in germlines
    if all('...' not in x for x in references.values()):
        printWarning('Germline reference sequences do not appear to contain IMGT-numbering spacers. Results may be incorrect.')

    # Define format operators
    try:
        __, writer, schema = getFormatOperators(format)
    except ValueError:
        printError('Invalid format %s.' % format)
    out_args['out_type'] = schema.out_type

    # Define output fields
    fields = list(schema.required)
    if extended:
        custom = IHMMuneReader.customFields(scores=True, regions=True, schema=schema)
        fields.extend(custom)

    # Parse and write output
    with open(aligner_file, 'r') as f:
        parse_iter = IHMMuneReader(f, seq_dict, references)
        germ_iter = (addGermline(x, references) for x in parse_iter)
        output = writeDb(germ_iter, fields=fields, aligner_file=aligner_file, total_count=total_count, 
                        annotations=annotations, asis_id=asis_id, partial=partial,
                        writer=writer, out_file=out_file, out_args=out_args)

    return output


def getArgParser():
    """
    Defines the ArgumentParser.

    Returns: 
      argparse.ArgumentParser
    """
    fields = dedent(
             '''
              output files:
                  db-pass
                      database of alignment records with functionality information,
                      V and J calls, and a junction region.
                  db-fail
                      database with records that fail due to no functionality information
                      (did not pass IMGT), no V call, no J call, or no junction region.

              universal output fields:
                  SEQUENCE_ID, SEQUENCE_INPUT, SEQUENCE_VDJ, SEQUENCE_IMGT,
                  FUNCTIONAL, IN_FRAME, STOP, MUTATED_INVARIANT, INDELS,
                  V_CALL, D_CALL, J_CALL,
                  V_SEQ_START, V_SEQ_LENGTH,
                  D_SEQ_START, D_SEQ_LENGTH, D_GERM_START, D_GERM_LENGTH,
                  J_SEQ_START, J_SEQ_LENGTH, J_GERM_START, J_GERM_LENGTH,
                  NP1_LENGTH, NP2_LENGTH,
                  JUNCTION_LENGTH, JUNCTION, GERMLINE_IMGT, 
                  FWR1_IMGT, FWR2_IMGT, FWR3_IMGT, FWR4_IMGT,
                  CDR1_IMGT, CDR2_IMGT, CDR3_IMGT

              imgt specific output fields:
                  V_GERM_START_IMGT, V_GERM_LENGTH_IMGT,
                  N1_LENGTH, N2_LENGTH, P3V_LENGTH, P5D_LENGTH, P3D_LENGTH, P5J_LENGTH,
                  D_FRAME, V_SCORE, V_IDENTITY, J_SCORE, J_IDENTITY,

              igblast specific output fields:
                  V_GERM_START_VDJ, V_GERM_LENGTH_VDJ,
                  V_EVALUE, V_SCORE, V_IDENTITY, V_CIGAR,
                  D_EVALUE, D_SCORE, D_IDENTITY, D_CIGAR,
                  J_EVALUE, J_SCORE, J_IDENTITY, J_CIGAR,
                  CDR3_IGBLAST, CDR3_IGBLAST_AA

              ihmm specific output fields:
                  V_GERM_START_VDJ, V_GERM_LENGTH_VDJ, VDJ_SCORE
                  
              10X specific output fields:
                  CELL, C_CALL, CONSCOUNT, UMICOUNT, 
                  V_CALL_10X, D_CALL_10X, J_CALL_10X,
                  JUNCTION_10X, JUNCTION_10X_AA
              ''')
                
    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', dest='command',
                                       help='Aligner used', metavar='')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Parent parser
    parser_parent = getCommonArgParser(db_in=False)

    # igblastn output parser
    parser_igblast = subparsers.add_parser('igblast', parents=[parser_parent],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='Process igblastn output.',
                                           description='Process igblastn output.')
    group_igblast = parser_igblast.add_argument_group('aligner parsing arguments')
    group_igblast.add_argument('-i', nargs='+', action='store', dest='aligner_files',
                                required=True,
                                help='''IgBLAST output files in format 7 with query sequence
                                     (igblastn argument \'-outfmt "7 std qseq sseq btop"\').''')
    group_igblast.add_argument('-r', nargs='+', action='store', dest='repo', required=True,
                                help='''List of folders and/or fasta files containing
                                     the same germline set used in the IgBLAST alignment. These
                                     reference sequences must contain IMGT-numbering spacers (gaps)
                                     in the V segment.''')
    group_igblast.add_argument('-s', action='store', nargs='+', dest='seq_files',
                                required=True,
                                help='''List of input FASTA files (with .fasta, .fna or .fa
                                     extension), containing sequences.''')
    group_igblast.add_argument('--10x', action='store', nargs='+', dest='cellranger_file',
                                help='''Table file containing 10X annotations (with .csv or .tsv
                                     extension).''')
    group_igblast.add_argument('--asis-id', action='store_true', dest='asis_id',
                                help='''Specify to prevent input sequence headers from being parsed
                                     to add new columns to database. Parsing of sequence headers requires
                                     headers to be in the pRESTO annotation format, so this should be specified
                                     when sequence headers are incompatible with the pRESTO annotation scheme.
                                     Note, unrecognized header formats will default to this behavior.''')
    group_igblast.add_argument('--asis-calls', action='store_true', dest='asis_calls',
                                help='''Specify to prevent gene calls from being parsed into standard allele names
                                     in both the IgBLAST output and reference database. Note, this requires
                                     the sequence identifiers in the reference sequence set and the IgBLAST
                                     database to be exact string matches.''')
    group_igblast.add_argument('--partial', action='store_true', dest='partial',
                                help='''If specified, include incomplete V(D)J alignments in
                                     the pass file instead of the fail file. An incomplete alignment
                                     is defined as a record for which a valid IMGT-gapped sequence 
                                     cannot be built or that is missing a V gene assignment, 
                                     J gene assignment, junction region, or productivity call.''')
    group_igblast.add_argument('--extended', action='store_true', dest='extended',
                               help='''Specify to include additional aligner specific fields in the output. 
                                     Adds the <VDJ>_SCORE, <VDJ>_IDENTITY, <VDJ>_EVALUE, and <VDJ>_CIGAR;
                                     FWR1_IMGT, FWR2_IMGT, FWR3_IMGT, and FWR4_IMGT; CDR1_IMGT, CDR2_IMGT, and
                                     CDR3_IMGT; CDR3_IGBLAST_NT and CDR3_IGBLAST_AA (requires IgBLAST
                                     version 1.5 or greater).''')
    parser_igblast.set_defaults(func=parseIgBLAST, amino_acid=False)

    # igblastp output parser
    parser_igblast_aa = subparsers.add_parser('igblast-aa', parents=[parser_parent],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='Process igblastp output.',
                                           description='Process igblastp output.')
    group_igblast_aa = parser_igblast_aa.add_argument_group('aligner parsing arguments')
    group_igblast_aa.add_argument('-i', nargs='+', action='store', dest='aligner_files',
                                  required=True,
                                  help='''IgBLAST output files in format 7 with query sequence
                                       (igblastp argument \'-outfmt "7 std qseq sseq btop"\').''')
    group_igblast_aa.add_argument('-r', nargs='+', action='store', dest='repo', required=True,
                                  help='''List of folders and/or fasta files containing
                                       the same germline set used in the IgBLAST alignment. These
                                       reference sequences must contain IMGT-numbering spacers (gaps)
                                       in the V segment.''')
    group_igblast_aa.add_argument('-s', action='store', nargs='+', dest='seq_files', required=True,
                                  help='''List of input FASTA files (with .fasta, .fna or .fa
                                       extension), containing sequences.''')
    group_igblast_aa.add_argument('--10x', action='store', nargs='+', dest='cellranger_file',
                                  help='''Table file containing 10X annotations (with .csv or .tsv extension).''')
    group_igblast_aa.add_argument('--asis-id', action='store_true', dest='asis_id',
                                  help='''Specify to prevent input sequence headers from being parsed
                                       to add new columns to database. Parsing of sequence headers requires
                                       headers to be in the pRESTO annotation format, so this should be specified
                                       when sequence headers are incompatible with the pRESTO annotation scheme.
                                       Note, unrecognized header formats will default to this behavior.''')
    group_igblast_aa.add_argument('--asis-calls', action='store_true', dest='asis_calls',
                                  help='''Specify to prevent gene calls from being parsed into standard allele names
                                       in both the IgBLAST output and reference database. Note, this requires
                                       the sequence identifiers in the reference sequence set and the IgBLAST
                                       database to be exact string matches.''')
    group_igblast_aa.add_argument('--extended', action='store_true', dest='extended',
                                  help='''Specify to include additional aligner specific fields in the output. 
                                       Adds V_SCORE, V_IDENTITY, V_EVALUE, and V_CIGAR;
                                       FWR1_IMGT, FWR2_IMGT, FWR3_IMGT; CDR1_IMGT, CDR2_IMGT.''')
    parser_igblast_aa.set_defaults(func=parseIgBLAST, partial=True, amino_acid=True)

    # IMGT aligner
    parser_imgt = subparsers.add_parser('imgt', parents=[parser_parent],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='''Process IMGT/HighV-Quest output
                                             (does not work with V-QUEST).''',
                                        description='''Process IMGT/HighV-Quest output
                                             (does not work with V-QUEST).''')
    group_imgt = parser_imgt.add_argument_group('aligner parsing arguments')
    group_imgt.add_argument('-i', nargs='+', action='store', dest='aligner_files',
                            help='''Either zipped IMGT output files (.zip or .txz) or a
                                 folder containing unzipped IMGT output files (which must
                                 include 1_Summary, 2_IMGT-gapped, 3_Nt-sequences,
                                 and 6_Junction).''')
    group_imgt.add_argument('-s', nargs='*', action='store', dest='seq_files', required=False,
                            help='''List of FASTA files (with .fasta, .fna or .fa
                                  extension) that were submitted to IMGT/HighV-QUEST. 
                                  If unspecified, sequence identifiers truncated by IMGT/HighV-QUEST
                                  will not be corrected.''')
    group_imgt.add_argument('-r', nargs='+', action='store', dest='repo', required=False,
                            help='''List of folders and/or fasta files containing
                                 the germline sequence set used by IMGT/HighV-QUEST. 
                                 These reference sequences must contain IMGT-numbering spacers (gaps)
                                 in the V segment. If unspecified, the germline sequence reconstruction 
                                 will not be included in the output.''')
    group_imgt.add_argument('--10x', action='store', nargs='+', dest='cellranger_file',
                            help='''Table file containing 10X annotations (with .csv or .tsv
                                 extension).''')
    group_imgt.add_argument('--asis-id', action='store_true', dest='asis_id',
                            help='''Specify to prevent input sequence headers from being parsed
                                 to add new columns to database. Parsing of sequence headers requires
                                 headers to be in the pRESTO annotation format, so this should be specified
                                 when sequence headers are incompatible with the pRESTO annotation scheme.
                                 Note, unrecognized header formats will default to this behavior.''')
    group_imgt.add_argument('--partial', action='store_true', dest='partial',
                            help='''If specified, include incomplete V(D)J alignments in
                                 the pass file instead of the fail file. An incomplete alignment
                                 is defined as a record that is missing a V gene assignment, 
                                 J gene assignment, junction region, or productivity call.''')
    group_imgt.add_argument('--extended', action='store_true', dest='extended',
                            help='''Specify to include additional aligner specific fields in the output. 
                                 Adds <VDJ>_SCORE and <VDJ>_IDENTITY>; FWR1_IMGT, FWR2_IMGT, FWR3_IMGT, and FWR4_IMGT;
                                 CDR1_IMGT, CDR2_IMGT, and CDR3_IMGT; and N1_LENGTH, N2_LENGTH, P3V_LENGTH, P5D_LENGTH, 
                                 P3D_LENGTH, P5J_LENGTH, and D_FRAME.''')
    parser_imgt.set_defaults(func=parseIMGT)

    # iHMMuneAlign Aligner
    parser_ihmm = subparsers.add_parser('ihmm', parents=[parser_parent],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Process iHMMune-Align output.',
                                        description='Process iHMMune-Align output.')
    group_ihmm = parser_ihmm.add_argument_group('aligner parsing arguments')
    group_ihmm.add_argument('-i', nargs='+', action='store', dest='aligner_files',
                             required=True,
                             help='''iHMMune-Align output file.''')
    group_ihmm.add_argument('-r', nargs='+', action='store', dest='repo', required=True,
                             help='''List of folders and/or FASTA files containing
                                   the set of germline sequences used by iHMMune-Align. These
                                   reference sequences must contain IMGT-numbering spacers (gaps)
                                   in the V segment.''')
    group_ihmm.add_argument('-s', action='store', nargs='+', dest='seq_files',
                             required=True,
                             help='''List of input FASTA files (with .fasta, .fna or .fa
                                  extension) containing sequences.''')
    group_ihmm.add_argument('--10x', action='store', nargs='+', dest='cellranger_file',
                                help='''Table file containing 10X annotations (with .csv or .tsv
                                     extension).''')
    group_ihmm.add_argument('--asis-id', action='store_true', dest='asis_id',
                             help='''Specify to prevent input sequence headers from being parsed
                                  to add new columns to database. Parsing of sequence headers requires
                                  headers to be in the pRESTO annotation format, so this should be specified
                                  when sequence headers are incompatible with the pRESTO annotation scheme.
                                  Note, unrecognized header formats will default to this behavior.''')
    group_ihmm.add_argument('--partial', action='store_true', dest='partial',
                             help='''If specified, include incomplete V(D)J alignments in
                                  the pass file instead of the fail file. An incomplete alignment
                                     is defined as a record for which a valid IMGT-gapped sequence 
                                     cannot be built or that is missing a V gene assignment, 
                                     J gene assignment, junction region, or productivity call.''')
    group_ihmm.add_argument('--extended', action='store_true', dest='extended',
                             help='''Specify to include additional aligner specific fields in the output. 
                                  Adds the path score of the iHMMune-Align hidden Markov model as VDJ_SCORE;
                                  FWR1_IMGT, FWR2_IMGT, FWR3_IMGT, and FWR4_IMGT; CDR1_IMGT, CDR2_IMGT, and
                                  CDR3_IMGT.''')
    parser_ihmm.set_defaults(func=parseIHMM)

    return parser
    
    
if __name__ == "__main__":
    """
    Parses command line arguments and calls main
    """
    parser = getArgParser()
    checkArgs(parser)
    args = parser.parse_args()
    args_dict = parseCommonArgs(args, in_arg='aligner_files')

    # Set no ID parsing if sequence files are not provided
    if 'seq_files' in args_dict and not args_dict['seq_files']:
        args_dict['asis_id'] = True

    # Delete
    if 'aligner_files' in args_dict: del args_dict['aligner_files']
    if 'seq_files' in args_dict: del args_dict['seq_files']
    if 'out_files' in args_dict: del args_dict['out_files']
    if 'command' in args_dict: del args_dict['command']
    if 'func' in args_dict: del args_dict['func']           

    # Call main
    for i, f in enumerate(args.__dict__['aligner_files']):
        args_dict['aligner_file'] = f
        args_dict['seq_file'] = args.__dict__['seq_files'][i] \
                                if args.__dict__['seq_files'] else None
        args_dict['out_file'] = args.__dict__['out_files'][i] \
                                if args.__dict__['out_files'] else None
        args_dict['cellranger_file'] = args.__dict__['cellranger_file'][i] \
                                if args.__dict__['cellranger_file'] else None
        args.func(**args_dict)
