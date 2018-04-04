"""
File I/O and logging functions
"""
# Info
__author__ = 'Namita Gupta, Jason Anthony Vander Heiden'
from changeo import __version__, __date__

# Imports
import csv
import os
import re
import sys
import tarfile
import zipfile
from itertools import chain, groupby, zip_longest
from tempfile import TemporaryDirectory
from Bio import SeqIO
from Bio.Alphabet import IUPAC
from Bio.Seq import Seq

# Presto and changeo imports
from presto.IO import getFileType
from changeo.Defaults import default_csv_size
from changeo.Receptor import allele_regex, v_allele_regex, d_allele_regex, j_allele_regex, \
                             parseAllele, decodeBTOP, encodeCIGAR, padAlignment, \
                             AIRRSchema, ChangeoSchema, Receptor

# System settings
csv.field_size_limit(default_csv_size)


class TSVReader:
    """
    Simple csv.DictReader wrapper to read format agnostic TSV files.
    """
    @property
    def fields(self):
        """
        Get list fields

        Returns:
          list : field names
        """
        return self.reader.fieldnames

    def __init__(self, handle):
        """
        Initializer

        Arguments:
          handle : handle to an open TSV file

        Returns:
          changeo.IO.TSVReader
        """
        # Arguments
        self.handle = handle
        self.reader = csv.DictReader(self.handle, dialect='excel-tab')

    def __iter__(self):
        """
        Iterator initializer.

        Returns:
          changeo.IO.TSVReader
        """
        return self

    def __next__(self):
        """
        Next method.

        Returns:
          changeo.Receptor.Receptor : Parsed Change-O data
        """
        # Get next row from reader iterator
        try:
            row = next(self.reader)
        except StopIteration:
            self.handle.close()
            raise StopIteration

        return row


class TSVWriter:
    """
    Simple csv.DictWriter wrapper to write format agnostic TSV files.
    """
    def __init__(self, handle, fields, header=True):
        """
        Initializer

        Arguments:
          handle : handle to an open output file
          fields : list of output field names
          header : if True write the header on initialization.

        Returns:
          changeo.IO.TSVWriter
        """
        # Arguments
        self.handle = handle
        self.fields = fields
        self.writer = csv.DictWriter(self.handle, fieldnames=self.fields,
                                     dialect='excel-tab', extrasaction='ignore')
        if header:
            self.writeHeader()

    def writeHeader(self):
        """
        Writes the header

        Returns:
          None
        """
        self.writer.writeheader()

    def writeDict(self, records):
        """
        Writes a row from a dictionary

        Arguments:
          records : dictionary of row data or an iterable of such objects.

        Returns:
          None
        """
        if isinstance(records, dict):
            self.writer.writerow(records)
        else:
            self.writer.writerows(records)


class ChangeoReader:
    """
    An iterator to read and parse Change-O formatted data.
    """

    @property
    def fields(self):
        """
        Get list fields

        Returns:
          list : field names
        """
        return self.reader.fieldnames

    @staticmethod
    def _receptor(record):
        """
        Parses a dictionary of fields in the Change-O to a Receptor object

        Arguments:
          record : dict with fields and values in the Change-O format

        Returns:
          dict : a parsed dict
        """
        # Parse fields
        result = {}
        for k, v in record.items():
            k = ChangeoSchema.asReceptor(k)
            result[k] = v

        return Receptor(result)

    def __init__(self, handle, receptor=True):
        """
        Initializer

        Arguments:
          handle : handle to an open Change-O formatted file
          receptor : if True (default) iteration returns a Receptor object, otherwise it returns a dictionary.

        Returns:
          changeo.Parsers.ChangeoReader
        """
        # Arguments
        self.handle = handle
        self.receptor = receptor
        self.reader = csv.DictReader(self.handle, dialect='excel-tab')
        self.reader.fieldnames = [n.strip().upper() for n in self.reader.fieldnames]

    def __iter__(self):
        """
        Iterator initializer.

        Returns:
          changeo.Parsers.ChangeoReader
        """
        return self

    def __next__(self):
        """
        Next method.

        Returns:
          changeo.Receptor.Receptor : Parsed Change-O data
        """
        # Get next row from reader iterator
        try:
            row = next(self.reader)
        except StopIteration:
            self.handle.close()
            raise StopIteration

        # Parse row
        if self.receptor:
            return ChangeoReader._receptor(row)
        else:
            return row


class ChangeoWriter:
    """
    Writes Change-O formatted data.
    """

    @staticmethod
    def _parseReceptor(record):
        """
        Parses a Receptor object to a Change-O dictionary

        Arguments:
          record : dict with fields and values in the Receptor format

        Returns:
          dict : a parsed dict
        """
        row = record.toDict()
        # Parse known fields
        result = {}
        for k, v in row.items():
            k = ChangeoSchema.asChangeo(k)
            result[k] = v

        return result

    def __init__(self, handle, fields=ChangeoSchema.fields(), header=True):
        """
        Initializer

        Arguments:
          handle : handle to an open output file
          fields : list of output field names
          header : if True write the header on initialization.

        Returns:
          changeo.Parsers.ChangeoWriter
        """
        # Arguments
        self.handle = handle
        self.fields = [n.strip().upper() for n in fields]
        self.writer = csv.DictWriter(self.handle, fieldnames=self.fields,
                                     dialect='excel-tab', extrasaction='ignore')
        if header:
            self.writeHeader()

    def writeHeader(self):
        """
        Writes the header

        Returns:
          None
        """
        self.writer.writeheader()

    def writeDict(self, records):
        """
        Writes a row from a Change-O dictionary

        Arguments:
          records : Change-O dictionary of row data or an interable of such objects.

        Returns:
          None
        """
        if isinstance(records, dict):
            self.writer.writerow(records)
        else:
            self.writer.writerows(records)

    def writeReceptor(self, records):
        """
        Writes a row from a Receptor object

        Arguments:
          records : a changeo.Receptor.Receptor object to write or an iterable of such objects.

        Returns:
          None
        """
        if isinstance(records, Receptor):
            row = ChangeoWriter._parseReceptor(records)
            self.writer.writerow(row)
        else:
            rows = (ChangeoWriter._parseReceptor(r) for r in records)
            self.writer.writerows(rows)


class AIRRReader:
    """
    An iterator to read and parse AIRR formatted data.
    """

    @property
    def fields(self):
        """
        Get list fields

        Returns:
          list : field names
        """
        return self.reader.fields

    @staticmethod
    def _receptor(record):
        """
        Parses a dictionary of fields in the AIRR to a Receptor object

        Arguments:
          record : dict with fields and values in the AIRR format

        Returns:
          dict : a parsed dict
        """
        # Parse fields
        result = {}
        for k, v in record.items():
            # Convert start positions to 0-based
            k = AIRRSchema.asReceptor(k)
            if v is not None and v != '' and k in AIRRSchema._start:
                v = str(int(v) + 1)
            result[k] = v

        for k in AIRRSchema._end:
            if k in result and result[k] is not None:
                start, length = AIRRSchema._end[k]
                result[length] = int(result[k]) - int(result[start]) + 1

        return Receptor(result)

    def __init__(self, handle, receptor=True):
        """
        Initializer

        Arguments:
          handle : handle to an open AIRR formatted file
          receptor : if True (default) iteration returns a Receptor object, otherwise it returns a dictionary.

        Returns:
          changeo.Parsers.AIRRReader
        """
        # Arguments
        self.handle = handle
        self.receptor = receptor

        # Define reader
        try:
            import airr
            self.reader = airr.read(self.handle, debug=False)
        except ImportError:
            sys.stderr.out(
                'Warning: AIRR standard library is not available. Falling back to non-validating TSV reader.')
            self.reader = TSVReader(self.handle)

    def __iter__(self):
        """
        Iterator initializer

        Returns:
          changeo.Parsers.AIRRReader
        """
        return self

    def __next__(self):
        """
        Next method

        Returns:
          changeo.Receptor.Receptor : Parsed Change-O data
        """
        # Get next row from reader iterator
        try:
            row = next(self.reader)
        except StopIteration:
            self.handle.close()
            raise StopIteration

        # Parse row
        if self.receptor:
            return AIRRReader._receptor(row)
        else:
            return row


class AIRRWriter:
    """
    Writes AIRR formatted data.
    """

    @staticmethod
    def _parseReceptor(record):
        """
        Parses a Receptor object to an AIRR dictionary

        Arguments:
          record : dict with fields and values in the Receptor format

        Returns:
          dict : a parsed dict
        """
        result = {}
        row = record.toDict()
        for k, v in row.items():
            # Convert start positions to 0-based
            if v is not None and v != '' and k in AIRRSchema._start:
                v = str(int(v) - 1)
            # Convert field names
            k = AIRRSchema.asAIRR(k, False)
            result[k] = v

        return result

    def __init__(self, handle, fields=AIRRSchema.fields()):
        """
        Initializer

        Arguments:
          handle : handle to an open output file
          fields : list of output field names

        Returns:
          changeo.Parsers.AIRRWriter
        """
        # Arguments
        self.handle = handle
        fields = [f.lower() for f in fields]

        # Define writer
        try:
            import airr
            self.writer = airr.create(self.handle, fields=fields, debug=False)
        except ImportError:
            sys.stderr.out(
                'Warning: AIRR standard library is not available. Falling back to non-validating TSV writer.')
            self.writer = TSVWriter(self.handle, fields=fields)

    def writeReceptor(self, records):
        """
        Writes a row from a Receptor object

        Arguments:
          records : a changeo.Receptor object to write or iterable of such objects.

        Returns:
          None
        """
        # TODO: define any additional fields before writing first row
        # if not self.writer.wroteMetadata:
        #     self.writer.addFields("changeo", row.keys())
        # print('\n===== RECORD START =====\n')
        # for k, v in row.items(): print(k, v)

        if isinstance(records, Receptor):
            row = AIRRWriter._parseReceptor(records)
            self.writer.write(row)
        else:
            rows = (AIRRWriter._parseReceptor(r) for r in records)
            for r in rows:  self.writer.write(r)


class IMGTReader:
    """
    An iterator to read and parse IMGT output files.
    """

    @property
    def fields(self):
        """
        List of ordered output field names.
        """
        return self._fields

    def __init__(self, summary, gapped, ntseq, junction, receptor=True):
        """
        Initializer

        Arguments:
          summary : handle to an open '1_Summary' IMGT/HighV-QUEST output file.
          gapped : handle to an open '2_IMGT-gapped-nt-sequences' IMGT/HighV-QUEST output file.
          ntseq: handle to an open '3_Nt-sequences' IMGT/HighV-QUEST output file.
          junction : handle to an open '6_Junction' IMGT/HighV-QUEST output file.
          receptor : if True (default) iteration returns an Receptor object, otherwise it returns a dictionary.

        Returns:
          change.Parsers.IMGTReader
        """
        # Arguments
        self.summary = summary
        self.gapped = gapped
        self.ntseq = ntseq
        self.junction = junction
        self.receptor = receptor

        # Define field list
        self._fields = ChangeoSchema.core_fields
        self._fields.extend(ChangeoSchema.region_fields)
        self._fields.extend(ChangeoSchema.junction_fields)
        self._fields.extend(ChangeoSchema.imgt_score_fields)

        # Open readers
        readers = [csv.DictReader(self.summary, delimiter='\t'),
                   csv.DictReader(self.gapped, delimiter='\t'),
                   csv.DictReader(self.ntseq, delimiter='\t'),
                   csv.DictReader(self.junction, delimiter='\t')]
        self.records = zip(*readers)

    @staticmethod
    def _parseFunctionality(summary):
        """
        Parse functionality information

        Arguments:
          summary : dictionary containing one row of the '1_Summary' file.

        Returns:
          dict : database entries for functionality information.
        """
        # Correct for new functionality column names
        if 'Functionality' not in summary:
            summary['Functionality'] = summary['V-DOMAIN Functionality']
            summary['Functionality comment'] = summary['V-DOMAIN Functionality comment']

        # Functionality parser
        def _functional():
            x = summary['Functionality']
            if x.startswith('productive'):
                return 'T'
            elif x.startswith('unproductive'):
                return 'F'
            else:
                return None

        # Junction frame parser
        def _inframe():
            x = summary['JUNCTION frame']
            return {'in-frame': 'T', 'out-of-frame': 'F'}.get(x, None)

        # Stop codon parser
        def _stop():
            x = summary['Functionality comment']
            return 'T' if 'stop codon' in x else 'F'

        # Mutated invariant parser
        def _invariant():
            x = summary['Functionality comment']
            y = summary['V-REGION potential ins/del']
            return 'T' if ('missing' in x) or ('missing' in y) else 'F'

        # Mutated invariant parser
        def _indels():
            x = summary['V-REGION potential ins/del']
            y = summary['V-REGION insertions']
            z = summary['V-REGION deletions']
            return 'T' if any([x, y, z]) else 'F'

        result = {}
        # Parse functionality information
        if 'No results' not in summary['Functionality']:
            result['FUNCTIONAL'] = _functional()
            result['IN_FRAME'] = _inframe()
            result['STOP'] = _stop()
            result['MUTATED_INVARIANT'] = _invariant()
            result['INDELS'] = _indels()

        return result

    @staticmethod
    def _parseGenes(summary):
        """
        Parse gene calls

        Arguments:
          summary : dictionary containing one row of the '1_Summary' file.

        Returns:
          dict : database entries for gene calls.
        """
        clean_regex = re.compile('(,)|(\(see comment\))')
        delim_regex = re.compile('\sor\s')

        # Gene calls
        result = {}
        v_call = summary['V-GENE and allele']
        d_call = summary['D-GENE and allele']
        j_call = summary['J-GENE and allele']
        result['V_CALL'] = delim_regex.sub(',', clean_regex.sub('', v_call)) if v_call else None
        result['D_CALL'] = delim_regex.sub(',', clean_regex.sub('', d_call)) if d_call else None
        result['J_CALL'] = delim_regex.sub(',', clean_regex.sub('', j_call)) if j_call else None

        return result

    @staticmethod
    def _parseSequences(gapped, ntseq):
        """
        Parses full length V(D)J sequences

        Arguments:
          gapped : dictionary containing one row of the '2_IMGT-gapped-nt-sequences' file.
          ntseq: dictionary containing one row of the '3_Nt-sequences' file.

        Returns:
          dict : database entries for fill length V(D)J sequences.
        """
        result = {}
        # Extract ungapped sequences
        if ntseq['V-D-J-REGION']:
            result['SEQUENCE_VDJ'] = ntseq['V-D-J-REGION']
        elif ntseq['V-J-REGION']:
            result['SEQUENCE_VDJ'] = ntseq['V-J-REGION']
        else:
            result['SEQUENCE_VDJ'] = ntseq['V-REGION']
        # Extract gapped sequences
        if gapped['V-D-J-REGION']:
            result['SEQUENCE_IMGT'] = gapped['V-D-J-REGION']
        elif gapped['V-J-REGION']:
            result['SEQUENCE_IMGT'] = gapped['V-J-REGION']
        else:
            result['SEQUENCE_IMGT'] = gapped['V-REGION']

        return result

    @staticmethod
    def _parseVPos(gapped, ntseq):
        """
        Parses V alignment positions

        Arguments:
          gapped : dictionary containing one row of the '2_IMGT-gapped-nt-sequences' file.
          ntseq: dictionary containing one row of the '3_Nt-sequences' file.

        Returns:
          dict : database entries for V query and germline alignment positions.
        """
        result = {}
        result['V_SEQ_START'] = ntseq['V-REGION start']
        result['V_SEQ_LENGTH'] = len(ntseq['V-REGION']) if ntseq['V-REGION'] else 0
        result['V_GERM_START_IMGT'] = 1
        result['V_GERM_LENGTH_IMGT'] = len(gapped['V-REGION']) if gapped['V-REGION'] else 0

        return result

    @staticmethod
    def _parseJuncPos(junction, db):
        """
        Parses junction N/P and D alignment positions

        Arguments:
          junction : dictionary containing one row of the '6_Junction' file.
          db : database containing V alignment information.

        Returns:
          dict : database entries for junction, N/P and D region alignment positions.
        """
        v_start = db['V_SEQ_START']
        v_length = db['V_SEQ_LENGTH']

        # First N/P length
        def _np1():
            nb = [junction['P3\'V-nt nb'],
                  junction['N-REGION-nt nb'],
                  junction['N1-REGION-nt nb'],
                  junction['P5\'D-nt nb']]
            return sum(int(i) for i in nb if i)

        # D start
        def _dstart():
            nb = [v_start,
                  v_length,
                  junction['P3\'V-nt nb'],
                  junction['N-REGION-nt nb'],
                  junction['N1-REGION-nt nb'],
                  junction['P5\'D-nt nb']]
            return sum(int(i) for i in nb if i)

        # Second N/P length
        def _np2():
            nb = [junction['P3\'D-nt nb'],
                  junction['N2-REGION-nt nb'],
                  junction['P5\'J-nt nb']]
            return sum(int(i) for i in nb if i)

        result = {}
        # Junction sequence
        result['JUNCTION'] = junction['JUNCTION']
        result['JUNCTION_AA'] = junction['JUNCTION (AA)']
        result['JUNCTION_LENGTH'] = len(junction['JUNCTION']) if junction['JUNCTION'] else 0

        # N/P and D alignment positions
        result['NP1_LENGTH'] = _np1()
        result['D_SEQ_START'] = _dstart()
        result['D_SEQ_LENGTH'] = int(junction['D-REGION-nt nb'] or 0)
        result['D_GERM_START'] = int(junction['5\'D-REGION trimmed-nt nb'] or 0) + 1
        result['D_GERM_LENGTH'] = int(junction['D-REGION-nt nb'] or 0)
        result['NP2_LENGTH'] = _np2()

        return result

    @staticmethod
    def _parseJPos(gapped, ntseq, junction, db):
        """
        Parses J alignment positions

        Arguments:
          gapped : dictionary containing one row of the '2_IMGT-gapped-nt-sequences' file.
          ntseq: dictionary containing one row of the '3_Nt-sequences' file.
          junction : dictionary containing one row of the '6_Junction' file.
          db : database containing V, N/P and D alignment information.

        Returns:
          dict : database entries for J region alignment positions.
        """

        # J start
        def _jstart():
            nb = [db['V_SEQ_START'],
                  db['V_SEQ_LENGTH'],
                  db['NP1_LENGTH'],
                  db['D_SEQ_LENGTH'],
                  db['NP2_LENGTH']]
            return sum(int(i) for i in nb if i)

        # J region alignment positions
        result = {}
        result['J_SEQ_START'] = _jstart()
        result['J_SEQ_LENGTH'] = len(ntseq['J-REGION']) if ntseq['J-REGION'] else 0
        result['J_GERM_START'] = int(junction['5\'J-REGION trimmed-nt nb'] or 0) + 1
        result['J_GERM_LENGTH'] = len(gapped['J-REGION']) if gapped['J-REGION'] else 0

        return result

    @staticmethod
    def _parseScores(summary):
        """
        Parse alignment scores

        Arguments:
          summary : dictionary containing one row of the '1_Summary' file.

        Returns:
          dict : database entries for alignment scores.
        """
        result = {}

        # V score
        try:
            result['V_SCORE'] = float(summary['V-REGION score'])
        except (TypeError, ValueError):
            result['V_SCORE'] = None
        # V identity
        try:
            result['V_IDENTITY'] = float(summary['V-REGION identity %']) / 100.0
        except (TypeError, ValueError):
            result['V_IDENTITY'] = 'None'
        # J score
        try:
            result['J_SCORE'] = float(summary['J-REGION score'])
        except (TypeError, ValueError):
            result['J_SCORE'] = None
        # J identity
        try:
            result['J_IDENTITY'] = float(summary['J-REGION identity %']) / 100.0
        except (TypeError, ValueError):
            result['J_IDENTITY'] = None

        return result

    @staticmethod
    def _parseJuncDetails(junction):
        """
        Parse detailed junction region information

        Arguments:
          junction : dictionary containing one row of the '6_Junction' file.

        Returns:
          dict : database entries for detailed D, N and P region information.
        """

        # D reading frame
        def _dframe():
            frame = None
            x = junction['D-REGION reading frame']
            if x:
                try:
                    frame = int(x)
                except ValueError:
                    m = re.search(r'reading frame ([0-9])', x).group(1)
                    frame = int(m)
            return frame

        # First N region length
        def _n1():
            nb = [junction['N-REGION-nt nb'], junction['N1-REGION-nt nb']]
            return sum(int(i) for i in nb if i)

        # D Frame and junction fields
        result = {}
        result['D_FRAME'] = _dframe()
        result['N1_LENGTH'] = _n1()
        result['N2_LENGTH'] = int(junction['N2-REGION-nt nb'] or 0)
        result['P3V_LENGTH'] = int(junction['P3\'V-nt nb'] or 0)
        result['P5D_LENGTH'] = int(junction['P5\'D-nt nb'] or 0)
        result['P3D_LENGTH'] = int(junction['P3\'D-nt nb'] or 0)
        result['P5J_LENGTH'] = int(junction['P5\'J-nt nb'] or 0)

        return result

    def parseRecord(self, summary, gapped, ntseq, junction):
        """
        Parses a single row from each IMTG file.

        Arguments:
          summary : dictionary containing one row of the '1_Summary' file.
          gapped : dictionary containing one row of the '2_IMGT-gapped-nt-sequences' file.
          ntseq : dictionary containing one row of the '3_Nt-sequences' file.
          junction : dictionary containing one row of the '6_Junction' file.

        Returns:
          dict : database entry for the row.
        """
        # Check that rows are syncronized
        id_set = [summary['Sequence ID'],
                  gapped['Sequence ID'],
                  ntseq['Sequence ID'],
                  junction['Sequence ID']]
        if len(set(id_set)) != 1:
            sys.exit('Error: IMGT files are corrupt starting with Summary file record %s' % id_set[0])

        # Initialize db with query ID and sequence
        db = {'SEQUENCE_ID': summary['Sequence ID'],
              'SEQUENCE_INPUT': summary['Sequence']}

        # Parse required fields
        db.update(IMGTReader._parseFunctionality(summary))
        db.update(IMGTReader._parseGenes(summary))
        db.update(IMGTReader._parseSequences(gapped, ntseq))
        db.update(IMGTReader._parseVPos(gapped, ntseq))
        db.update(IMGTReader._parseJuncPos(junction, db))
        db.update(IMGTReader._parseJPos(gapped, ntseq, junction, db))

        # Parse optional fields
        db.update(IMGTReader._parseScores(summary))
        db.update(getRegions(db['SEQUENCE_IMGT'], db['JUNCTION_LENGTH']))
        db.update(IMGTReader._parseJuncDetails(junction))

        return db

    def __iter__(self):
        """
        Iterator initializer.

        Returns:
          changeo.Parsers.IMGTReader
        """
        return self

    def __next__(self):
        """
        Next method.

        Returns:
          changeo.Receptor.Receptor : parsed IMGT/HighV-QUEST result as an Receptor (receptor=True) or dictionary (receptor=False).
        """
        # Get next set of records from dictionary readers
        try:
            summary, gapped, ntseq, junction = next(self.records)
        except StopIteration:
            raise StopIteration

        db = self.parseRecord(summary, gapped, ntseq, junction)

        if self.receptor:
            return Receptor(db)
        else:
            return db


class IgBLASTReader:
    """
    An iterator to read and parse IgBLAST output files
    """
    # IgBLAST extra summary fields
    _summary_fields = ['REV_COMP']

    @property
    def fields(self):
        """
        List of ordered output field names.
        """
        return self._fields

    def __init__(self, igblast, seq_dict, repo_dict, asis_calls=False, receptor=True):
        """
        Initializer.

        Arguments:
          igblast : handle to an open IgBLAST output file written with '-outfmt 7 std qseq sseq btop'.
          seq_dict : dictionary of query sequences;
                     sequence descriptions as keys with original query sequences as SeqRecord values.
          repo_dict : dictionary of IMGT gapped germline sequences.
          asis_calls : if True do not parse gene calls for allele names.
          receptor : if True (default) iteration returns an Receptor object, otherwise it returns a dictionary.

        Returns:
          changeo.Parsers.IgBLASTReader
        """
        # Arguments
        self.igblast = igblast
        self.seq_dict = seq_dict
        self.repo_dict = repo_dict
        self.asis_calls = asis_calls
        self.receptor = receptor

        # Define field list
        self._fields = ChangeoSchema.core_fields
        self._fields.extend(self._summary_fields)
        self._fields.extend(ChangeoSchema.region_fields)
        self._fields.extend(ChangeoSchema.igblast_score_fields)
        self._fields.extend(ChangeoSchema.igblast_cdr3_fields)

        # Define parsing blocks
        self.groups = groupby(self.igblast, lambda x: not re.match('# IGBLASTN', x))

    @staticmethod
    def _parseQueryChunk(chunk):
        """
        Parse query section

        Arguments:
          chunk : list of strings

        Returns:
          str : query identifier
        """
        # Extract query id from comments
        query = next((x for x in chunk if x.startswith('# Query:')))

        return query.replace('# Query: ', '', 1)

    @staticmethod
    def _parseSummaryChunk(chunk):
        """
        Parse summary section

        Args:
            chunk: list of strings

        Returns:
            dict : summary section.
        """
        # Mapping for field names in the summary section
        summary_map = {'Top V gene match': 'v_match',
                       'Top D gene match': 'd_match',
                       'Top J gene match': 'j_match',
                       'Chain type': 'chain',
                       'stop codon': 'stop',
                       'V-J frame': 'frame',
                       'Productive': 'productive',
                       'Strand': 'strand'}

        # Extract column names from comments
        f = next((x for x in chunk if x.startswith('# V-(D)-J rearrangement summary')))
        f = re.search('summary for query sequence \((.+)\)\.', f).group(1)
        columns = [summary_map[x.strip()] for x in f.split(',')]

        # Extract first row as a list
        row = next((x.split('\t') for x in chunk if not x.startswith('#')))

        # Populate template dictionary with parsed fields
        summary = {v: None for v in summary_map.values()}
        summary.update(dict(zip(columns, row)))

        return summary

    @staticmethod
    def _parseSubregionChunk(chunk):
        """
        Parse CDR3 sequences generated by IgBLAST

        Args:
          chunk: list of strings

        Returns:
          dict : nucleotide and amino acid CDR3 sequences
        """
        # Example:
        #   # Sub-region sequence details (nucleotide sequence, translation, start, end)
        #   CDR3  CAACAGTGGAGTAGTTACCCACGGACG QQWSSYPRT	248	287

        # Define column names
        cdr3_map = {'nucleotide sequence': 'CDR3_IGBLAST_NT',
                    'translation': 'CDR3_IGBLAST_AA',
                    'start': 'CDR3_IGBLAST_START',
                    'end': 'CDR3_IGBLAST_END'}

        # Extract column names from comments
        f = next((x for x in chunk if x.startswith('# Sub-region sequence details')))
        f = re.search('sequence details \((.+)\)', f).group(1)
        columns = [cdr3_map[x.strip()] for x in f.split(',')]

        # Extract first CDR3 as a list and remove the CDR3 label
        rows = next((x.split('\t') for x in chunk if x.startswith('CDR3')))[1:]

        # Populate dictionary with parsed fields
        cdr = {v: None for v in columns}
        cdr.update(dict(zip(columns, rows)))

        return cdr

    @staticmethod
    def _parseHitsChunk(chunk):
        """
        Parse hits section

        Args:
          chunk: list of strings

        Returns:
          list: hit table as a list of dictionaries
        """
        # Extract column names from comments
        f = next((x for x in chunk if x.startswith('# Fields:')))
        columns = chain(['segment'], f.replace('# Fields:', '', 1).split(','))
        columns = [x.strip() for x in columns]
        # Split non-comment rows into a list of lists
        rows = [x.split('\t') for x in chunk if not x.startswith('#')]
        # Create list of dictionaries containing hits
        hits = [{k: x[i] for i, k in enumerate(columns)} for x in rows]

        return hits

    # Parse summary results
    @staticmethod
    def _parseSummarySection(summary, db, asis_calls=False):
        """
        Parse summary section

        Arguments:
          summary :  summary section dictionary return by parseBlock
          db : initial database dictionary.
          asis_calls : if True do not parse gene calls for allele names.

        Returns:
          dict : db of results.
        """
        result = {}
        # Parse V, D, and J calls
        if not asis_calls:
            v_call = parseAllele(summary['v_match'], v_allele_regex, action='list')
            d_call = parseAllele(summary['d_match'], d_allele_regex, action='list')
            j_call = parseAllele(summary['j_match'], j_allele_regex, action='list')
            result['V_CALL'] = ','.join(v_call) if v_call else None
            result['D_CALL'] = ','.join(d_call) if d_call else None
            result['J_CALL'] = ','.join(j_call) if j_call else None
        else:
            result['V_CALL'] = None if summary['v_match'] == 'N/A' else summary['v_match']
            result['D_CALL'] = None if summary['d_match'] == 'N/A' else summary['d_match']
            result['J_CALL'] = None if summary['j_match'] == 'N/A' else summary['j_match']

        # Parse quality information
        result['STOP'] = 'T' if summary['stop'] == 'Yes' else 'F'
        result['IN_FRAME'] = 'T' if summary['frame'] == 'In-frame' else 'F'
        result['FUNCTIONAL'] = 'T' if summary['productive'] == 'Yes' else 'F'

        # Reverse complement input sequence if required
        if summary['strand'] == '-':
            seq_rc = Seq(db['SEQUENCE_INPUT'], IUPAC.ambiguous_dna).reverse_complement()
            result['SEQUENCE_INPUT'] = str(seq_rc)
            result['REV_COMP'] = 'T'
        else:
            result['REV_COMP'] = 'F'

        return result

    @staticmethod
    def _parseSubregionSection(section, sequence):
        """
        Parse subregion section

        Arguments:
          section :  subregion section dictionary return by parseBlock
          sequence : input sequence

        Returns:
          dict : db of results.
        """
        # Extract junction
        junc_start = int(section['CDR3_IGBLAST_START']) - 3
        junc_end = int(section['CDR3_IGBLAST_END']) + 3
        junc_seq = sequence[(junc_start - 1):junc_end]
        junc_len = len(junc_seq)

        # Translation
        junc_tmp = junc_seq.replace('-', 'N').replace('.', 'N')
        if junc_len % 3 > 0:  junc_tmp = junc_tmp[:junc_len - junc_len % 3]
        junc_aa = str(Seq(junc_tmp).translate())

        # Build return values
        return {'JUNCTION': junc_seq,
                'JUNCTION_AA': junc_aa,
                'JUNCTION_LENGTH': junc_len,
                'JUNCTION_START': junc_start,
                'JUNCTION_END': junc_end}

    @staticmethod
    def _parseVHitPos(v_hit):
        """
        Parse V alignment positions

        Arguments:
          v_hit :  V alignment row from the hit table

        Returns:
          dict: db of D starts and lengths
        """
        result = {}
        # Germline positions
        result['V_GERM_START_VDJ'] = int(v_hit['s. start'])
        result['V_GERM_LENGTH_VDJ'] = int(v_hit['s. end']) - result['V_GERM_START_VDJ'] + 1
        # Query sequence positions
        result['V_SEQ_START'] = int(v_hit['q. start'])
        result['V_SEQ_LENGTH'] = int(v_hit['q. end']) - result['V_SEQ_START'] + 1
        result['INDELS'] = 'F' if int(v_hit['gap opens']) == 0 else 'T'

        return result

    @staticmethod
    def _parseDHitPos(d_hit, overlap):
        """
        Parse D alignment positions

        Arguments:
          d_hit :  D alignment row from the hit table
          overlap : V-D overlap length

        Returns:
          dict: db of D starts and lengths
        """
        result = {}
        # Query sequence positions
        result['D_SEQ_START'] = int(d_hit['q. start']) + overlap
        result['D_SEQ_LENGTH'] = max(int(d_hit['q. end']) - result['D_SEQ_START'] + 1, 0)
        # Germline positions
        result['D_GERM_START'] = int(d_hit['s. start']) + overlap
        result['D_GERM_LENGTH'] = max(int(d_hit['s. end']) - result['D_GERM_START'] + 1, 0)

        return result

    @staticmethod
    def _parseJHitPos(j_hit, overlap):
        """
        Parse J alignment positions

        Arguments:
          j_hit :  J alignment row from the hit table
          overlap : D-J or V-J overlap length

        Returns:
          dict: db of J starts and lengths
        """
        result = {}
        result['J_SEQ_START'] = int(j_hit['q. start']) + overlap
        result['J_SEQ_LENGTH'] = max(int(j_hit['q. end']) - result['J_SEQ_START'] + 1, 0)
        result['J_GERM_START'] = int(j_hit['s. start']) + overlap
        result['J_GERM_LENGTH'] = max(int(j_hit['s. end']) - result['J_GERM_START'] + 1, 0)

        return result

    @staticmethod
    def _removeInsertions(seq, hits, start):
        """
        Remove insertions from aligned query sequences

        Arguments:
          seq :  sequence to modify
          hits : hit table row for the sequence
          start : start position of the query sequence

        Returns:
          str : modified sequence
        """
        if 'subject seq' not in hits or 'query seq' not in hits:
            return None

        for m in re.finditer(r'-', hits['subject seq']):
            ins = m.start()
            seq += hits['query seq'][start:ins]
            start = ins + 1
        seq += hits['query seq'][start:]

        return seq

    @staticmethod
    def _parseVHits(hits, db):
        """
        Parse V hit sub-table

        Arguments:
          hits :  hit table as a list of dictionaries.
          db : database dictionary containing summary results.

        Returns:
          dict : db of results.
        """
        result = {}
        seq_vdj = db['SEQUENCE_VDJ']
        v_hit = next(x for x in hits if x['segment'] == 'V')

        # Alignment positions
        result.update(IgBLASTReader._parseVHitPos(v_hit))
        # Update VDJ sequence, removing insertions
        result['SEQUENCE_VDJ'] = IgBLASTReader._removeInsertions(seq_vdj, v_hit, 0)

        return result

    @staticmethod
    def _parseDHits(hits, db):
        """
        Parse D hit sub-table

        Arguments:
          hits :  hit table as a list of dictionaries.
          db : database dictionary containing summary and V results.

        Returns:
          dict : db of results.
        """
        result = {}
        seq_vdj = db['SEQUENCE_VDJ']
        d_hit = next(x for x in hits if x['segment'] == 'D')

        # TODO:  this is kinda gross.  not sure how else to fix the alignment overlap problem though.
        # Determine N-region length and amount of J overlap with V or D alignment
        overlap = 0
        if db['V_CALL']:
            np1_len = int(d_hit['q. start']) - (db['V_SEQ_START'] + db['V_SEQ_LENGTH'])
            if np1_len < 0:
                result['NP1_LENGTH'] = 0
                overlap = abs(np1_len)
            else:
                result['NP1_LENGTH'] = np1_len
                np1_start = db['V_SEQ_START'] + db['V_SEQ_LENGTH'] - 1
                np1_end = int(d_hit['q. start']) - 1
                if seq_vdj is not None:
                    seq_vdj += db['SEQUENCE_INPUT'][np1_start:np1_end]

        # D alignment positions
        result.update(IgBLASTReader._parseDHitPos(d_hit, overlap))
        # Update VDJ sequence, removing insertions
        result['SEQUENCE_VDJ'] = IgBLASTReader._removeInsertions(seq_vdj, d_hit, overlap)

        return result

    @staticmethod
    def _parseJHits(hits, db):
        """
        Parse J hit sub-table

        Arguments:
          hits :  hit table as a list of dictionaries.
          db : database dictionary containing summary, V and D results.

        Returns:
          dict : db of results.
        """
        result = {}
        seq_vdj = db['SEQUENCE_VDJ']
        j_hit = next(x for x in hits if x['segment'] == 'J')

        # TODO:  this is kinda gross.  not sure how else to fix the alignment overlap problem though.
        # Determine N-region length and amount of J overlap with V or D alignment
        overlap = 0
        if db['D_CALL']:
            np2_len = int(j_hit['q. start']) - (db['D_SEQ_START'] + db['D_SEQ_LENGTH'])
            if np2_len < 0:
                result['NP2_LENGTH'] = 0
                overlap = abs(np2_len)
            else:
                result['NP2_LENGTH'] = np2_len
                n2_start = db['D_SEQ_START'] + db['D_SEQ_LENGTH'] - 1
                n2_end = int(j_hit['q. start']) - 1
                if seq_vdj is not None:
                    seq_vdj += db['SEQUENCE_INPUT'][n2_start: n2_end]
        elif db['V_CALL']:
            np1_len = int(j_hit['q. start']) - (db['V_SEQ_START'] + db['V_SEQ_LENGTH'])
            if np1_len < 0:
                result['NP1_LENGTH'] = 0
                overlap = abs(np1_len)
            else:
                result['NP1_LENGTH'] = np1_len
                np1_start = db['V_SEQ_START'] + db['V_SEQ_LENGTH'] - 1
                np1_end = int(j_hit['q. start']) - 1
                if seq_vdj is not None:
                    seq_vdj += db['SEQUENCE_INPUT'][np1_start: np1_end]
        else:
            result['NP1_LENGTH'] = 0

        # J alignment positions
        result.update(IgBLASTReader._parseJHitPos(j_hit, overlap))
        # Update VDJ sequence, removing insertions
        result['SEQUENCE_VDJ'] = IgBLASTReader._removeInsertions(seq_vdj, j_hit, overlap)

        return result

    @staticmethod
    def _parseHitScores(hits, segment):
        """
        Parse alignment scores

        Arguments:
          hits :  hit table as a list of dictionaries.
          segment : segment name; one of 'V', 'D' or 'J'.

        Returns:
          dict : scores
        """
        result = {}
        s_hit = next(x for x in hits if x['segment'] == segment)

        # Score
        try:
            result['%s_SCORE' % segment] = float(s_hit['bit score'])
        except (TypeError, ValueError):
            result['%s_SCORE' % segment] = None
        # Identity
        try:
            result['%s_IDENTITY' % segment] = float(s_hit['% identity']) / 100.0
        except (TypeError, ValueError):
            result['%s_IDENTITY' % segment] = None
        # E-value
        try:
            result['%s_EVALUE' % segment] = float(s_hit['evalue'])
        except (TypeError, ValueError):
            result['%s_EVALUE' % segment] = None
        # BTOP
        try:
            result['%s_BTOP' % segment] = s_hit['BTOP']
        except (KeyError, TypeError, ValueError):
            result['%s_BTOP' % segment] = None
        # CIGAR
        try:
            align = decodeBTOP(s_hit['BTOP'])
            align = padAlignment(align, int(s_hit['q. start']) - 1, int(s_hit['s. start']) - 1)
            result['%s_CIGAR' % segment] = encodeCIGAR(align)
        except (KeyError, TypeError, ValueError):
            result['%s_CIGAR' % segment] = None

        return result

    def parseBlock(self, block):
        """
        Parses an IgBLAST result into separate sections

        Arguments:
          block : an iterator from itertools.groupby containing a single IgBLAST result.

        Returns:
          dict : a parsed results block;
                 with the keys 'query' (sequence identifier as a string),
                 'summary' (dictionary of the alignment summary),
                 'subregion' (dictionary of IgBLAST CDR3 sequences), and
                 'hits' (VDJ hit table as a list of dictionaries).
                 Returns None if the block has no data that can be parsed.
        """
        # Parsing info
        #
        #   Columns for non-hit-table sections
        #     'V-(D)-J rearrangement summary': (Top V gene match, Top D gene match, Top J gene match, Chain type, stop codon, V-J frame, Productive, Strand)
        #     'V-(D)-J junction details': (V end, V-D junction, D region, D-J junction, J start)
        #     'Alignment summary': (from, to, length, matches, mismatches, gaps, percent identity)
        #     'subregion': (nucleotide sequence, translation)
        #
        #   Ignored sections
        #     'junction': '# V-(D)-J junction details'
        #     'v_alignment': '# Alignment summary'
        #
        #   Hit table fields for -outfmt "7 std qseq sseq btop"
        #     0:  segment
        #     1:  query id
        #     2:  subject id
        #     3:  % identity
        #     4:  alignment length
        #     5:  mismatches
        #     6:  gap opens
        #     7:  gaps
        #     8:  q. start
        #     9:  q. end
        #    10:  s. start
        #    11:  s. end
        #    12:  evalue
        #    13:  bit score
        #    14:  query seq
        #    15:  subject seq
        #    16:  btop
        # Map of valid block parsing keys and functions
        chunk_map = {'query': ('# Query:', self._parseQueryChunk),
                     'summary': ('# V-(D)-J rearrangement summary', self._parseSummaryChunk),
                     'subregion': ('# Sub-region sequence details', self._parseSubregionChunk),
                     'hits': ('# Hit table', self._parseHitsChunk)}

        # Parsing chunks
        results = {}
        for match, chunk in groupby(block, lambda x: x != '\n'):
            if match:
                # Strip whitespace and convert to list
                chunk = [x.strip() for x in chunk]

                # Parse non-query sections
                chunk_dict = {k: f(chunk) for k, (v, f) in chunk_map.items() if chunk[0].startswith(v)}
                results.update(chunk_dict)

        return results if results else None

    def parseSections(self, sections):
        """
        Parses an IgBLAST sections into a db dictionary

        Arguments:
            sections : dictionary of parsed sections from parseBlock.

        Returns:
          dict : db entries.
        """

        # Initialize dictionary with input sequence and id
        db = {}
        if 'query' in sections:
            query = sections['query']
            db['SEQUENCE_ID'] = query
            db['SEQUENCE_INPUT'] = str(self.seq_dict[query].seq)

        # Parse summary section
        if 'summary' in sections:
            db.update(self._parseSummarySection(sections['summary'], db, asis_calls=self.asis_calls))

        # Parse hit table
        if 'hits' in sections:
            db['SEQUENCE_VDJ'] = ''
            if db['V_CALL']:
                db.update(self._parseVHits(sections['hits'], db))
                db.update(self._parseHitScores(sections['hits'], 'V'))
            if db['D_CALL']:
                db.update(self._parseDHits(sections['hits'], db))
                db.update(self._parseHitScores(sections['hits'], 'D'))
            if db['J_CALL']:
                db.update(self._parseJHits(sections['hits'], db))
                db.update(self._parseHitScores(sections['hits'], 'J'))

        # Create IMGT-gapped sequence
        if ('V_CALL' in db and db['V_CALL']) and ('SEQUENCE_VDJ' in db and db['SEQUENCE_VDJ']):
            imgt_dict = gapV(db['SEQUENCE_VDJ'],
                             v_germ_start=db['V_GERM_START_VDJ'],
                             v_germ_length=db['V_GERM_LENGTH_VDJ'],
                             v_call=db['V_CALL'],
                             references=self.repo_dict,
                             asis_calls=self.asis_calls)
            db.update(imgt_dict)

        # Add junction
        if 'subregion' in sections:
            if 'CDR3_IGBLAST_START' in sections['subregion']:
                junc_dict = self._parseSubregionSection(sections['subregion'], db['SEQUENCE_INPUT'])
                db.update(junc_dict)
            elif ('J_CALL' in db and db['J_CALL']) and ('SEQUENCE_IMGT' in db and db['SEQUENCE_IMGT']):
                junc_dict = inferJunction(db['SEQUENCE_IMGT'],
                                          j_germ_start=db['J_GERM_START'],
                                          j_germ_length=db['J_GERM_LENGTH'],
                                          j_call=db['J_CALL'],
                                          references=self.repo_dict,
                                          asis_calls=self.asis_calls)
                db.update(junc_dict)

        # Add IgBLAST CDR3 sequences
        if 'subregion' in sections:
            # Sequences already parsed into dict by parseBlock
            db.update(sections['subregion'])
        else:
            # Section does not exist (ie, older version of IgBLAST or CDR3 not found)
            db.update(dict(zip(ChangeoSchema.igblast_cdr3_fields, [None, None])))

        # Add FWR and CDR regions
        db.update(getRegions(db.get('SEQUENCE_IMGT', None), db.get('JUNCTION_LENGTH', None)))

        return db

    def __iter__(self):
        """
        Iterator initializer.

        Returns:
          changeo.Parsers.IgBLASTReader
        """
        return self

    def __next__(self):
        """
        Next method.

        Returns:
          changeo.Receptor.Receptor : parsed IMGT/HighV-QUEST result as an Receptor (receptor=True) or dictionary (receptor=False).
        """
        # Get next block from groups iterator
        try:
            match = False
            block = None
            while not match:
                match, block = next(self.groups)
        except StopIteration:
            raise StopIteration

        # Parse block
        sections = self.parseBlock(block)
        db = self.parseSections(sections)

        if self.receptor:
            return Receptor(db)
        else:
            return db


class IHMMuneReader:
    """
    An iterator to read and parse iHMMune-Align output files.
    """
    # iHMMuneAlign columns
    # Courtesy of Katherine Jackson
    #
    #  1: Identifier - sequence identifer from FASTA input file
    #  2: IGHV - IGHV gene match from the IGHV repertoire, if multiple genes had equally
    #            good alignments both will be listed, if indels were found this will be
    #            listed, in case of multiple IGHV all further data is reported with
    #            respect to the first listed gene
    #  3: IGHD - IGHD gene match, if no IGHD could be found or the IGHD that was found
    #            failed to meet confidence criteria this will be 'NO_DGENE_ALIGNMENT'
    #  4: IGHJ - IGHJ gene match, only a single best matching IGHJ is reported, if indels
    #            are found then 'indel' will be listed
    #  5: V-REGION - portion of input sequence that matches to the germline IGHV, were
    #                nucleotide are missing at start or end the sequence is padded back
    #                to full length with '.' (the exonuclease loss from the end of the
    #                gene will therefore be equal to the number of '.' characters at the
    #                5` end), mismatches between germline and rearranged are in uppercase,
    #                matches are in lowercase
    #  6: N1-REGION - sequence between V- and D-REGIONs
    #  7: D-REGION - portion of input sequence that matches to the germline IGHD
    #                (model doesn't currently permit indels in the IGHD), where IGHD is
    #                reported as 'NO_DGENE_ALIGNMENT' this field contains all nucleotides
    #                between the V- and J-REGIONs
    #  8: N2-REGION - sequence between D- and J-REGIONs
    #  9: J-REGION - portion of the input sequence that matches germline IGHJ, padded
    #                5` and 3` to length of germline match
    # 10: V mutation count - count of mismatches in the V-REGION
    # 11: D mutation count - count of mismatches in the D-REGION
    # 12: J mutation count - count of mismatches in the J-REGION
    # 13: count of ambigious nts - count of 'n' or 'x' nucleotides in the input sequence
    # 14: IGHJ in-frame - 'true' is IGHJ is in-frame and 'false' if IGHJ is out-of-frame,
    #                     WARNING indels and germline IGHV database sequences that are
    #                     not RF1 can cause this to report inaccurately
    # 15: IGHV start offset - offset for start of alignment between input sequence and
    #                         germline IGHV
    #                         NOTE: appears to be base 1 indexing.
    # 16: stop codons - count of stop codons in the sequence, WARNING indels and germline
    #                   IGHV database sequence that are not RF can cause this to be inaccurate
    # 17: IGHD probability - probability that N-nucleotide addition could have created the
    #                        D-REGION sequence
    # 18: HMM path score - path score from HMM
    # 19: reverse complement - 0 for no reverse complement, 1 if alignment was to reverse
    #                          complement NOTE currently this version only functions with
    #                          input in coding orientation
    # 20: mutations in common region - count of mutations in common region, which is a
    #                                  portion of the IGHV that is highly conserved,
    #                                  mutations in this region are used to set various
    #                                  probabilities in the HMM
    # 21: ambigious nts in common region - count of 'n' or 'x' nucleotides in the
    #                                      common region
    # 22: IGHV start offset  - offset for start of alignment between input sequence and
    #                          germline IGHV
    #                          NOTE: appears to be base 0 indexing.
    #                          NOTE: don't know if this differs from 15; it doesn't appear to.
    # 23: IGHV gene length - length of IGHV gene
    # 24: A score - A score probability is calculated from the common region mutations
    #               and is used for HMM calculations relating to expected mutation
    #               probability at different positions in the rearrangement
    ihmmune_fields = ['SEQUENCE_ID',
                      'V_CALL',
                      'D_CALL',
                      'J_CALL',
                      'V_SEQ',
                      'NP1_SEQ',
                      'D_SEQ',
                      'NP2_SEQ',
                      'J_SEQ',
                      'V_MUT',
                      'D_MUT',
                      'J_MUT',
                      'NX_COUNT',
                      'J_INFRAME',
                      'V_SEQ_START',
                      'STOP_COUNT',
                      'D_PROB',
                      'HMM_SCORE',
                      'RC',
                      'COMMON_MUT',
                      'COMMON_NX_COUNT',
                      'V_SEQ_START',
                      'V_SEQ_LENGTH',
                      'A_SCORE']

    # iHMMUne-Align score fields
    _score_fields = ['HMM_SCORE']

    @property
    def fields(self):
        """
        List of ordered output field names.
        """
        return self._fields

    def __init__(self, ihmmune, seq_dict, repo_dict, receptor=True):
        """
        Initializer

        Arguments:
          ihmmune : handle to an open iHMMune-Align output file.
          seq_dict : dictionary with sequence descriptions as keys mapping to the SeqRecord containing
                    the original query sequences.
          repo_dict : dictionary of IMGT gapped germline sequences.
          receptor : if True (default) iteration returns an Receptor object, otherwise it returns a dictionary

        Returns:
          changeo.Parsers.IHMMuneReader
        """
        # Arguments
        self.ihmmune = ihmmune
        self.seq_dict = seq_dict
        self.repo_dict = repo_dict
        self.receptor = receptor

        # Define field list
        self._fields = ChangeoSchema.core_fields
        self._fields.extend(ChangeoSchema.region_fields)
        self._fields.extend(ChangeoSchema.ihmm_score_fields)

        # Open reader
        self.records = csv.DictReader(self.ihmmune, fieldnames=IHMMuneReader.ihmmune_fields,
                                      delimiter=';', quotechar='"')

    @staticmethod
    def _parseFunctionality(record):
        """
        Parse functionality information

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.

        Returns:
          dict : database entries containing functionality information.
        """

        # Functional
        def _functional():
            if not record['V_CALL'] or \
                    record['V_CALL'].startswith('NA - ') or \
                    record['J_INFRAME'] != 'true' or \
                    not record['J_CALL'] or \
                    record['J_CALL'] == 'NO_JGENE_ALIGNMENT' or \
                    int(record['STOP_COUNT']) > 0:
                return 'F'
            else:
                return 'T'

        # Stop codon
        def _stop():
            return 'T' if int(record['STOP_COUNT']) > 0 else 'F'

        # J in-frame
        def _inframe():
            return 'T' if record['J_INFRAME'] == 'true' else 'F'

        # Indels
        def _indels():
            check = [x is not None and 'indels' in x \
                     for x in [record['V_CALL'], record['D_CALL'], record['J_CALL']]]
            return 'T' if any(check) else 'F'

        # Parse functionality
        result = {}
        result['FUNCTIONAL'] = _functional()
        result['IN_FRAME'] = _inframe()
        result['STOP'] = _stop()
        result['INDELS'] = _indels()

        return result

    @staticmethod
    def _parseGenes(record):
        """
        Parse gene calls

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.

        Returns:
          dict : database entries for gene calls.
        """
        result = {}
        v_call = parseAllele(record['V_CALL'], v_allele_regex, action='list')
        d_call = parseAllele(record['D_CALL'], d_allele_regex, action='list')
        j_call = parseAllele(record['J_CALL'], j_allele_regex, action='list')
        result['V_CALL'] = ','.join(v_call) if v_call else None
        result['D_CALL'] = ','.join(d_call) if d_call else None
        result['J_CALL'] = ','.join(j_call) if j_call else None

        return result

    @staticmethod
    def _parseNPHit(record):
        """
        Parse N/P region alignment information

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.

        Returns:
          dict : database entries containing N/P region lengths.
        """
        # N/P lengths
        result = {}
        result['NP1_LENGTH'] = len(record['NP1_SEQ'])
        result['NP2_LENGTH'] = len(record['NP2_SEQ'])

        return result

    @staticmethod
    def _parseVHit(record, db):
        """
        Parse V alignment information

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.
          db : database containing V and D alignment information.

        Returns:
          dict : database entries containing V call and alignment positions.
        """
        # Default return
        result = {'V_SEQ_START': None,
                  'V_SEQ_LENGTH': None,
                  'V_GERM_START': None,
                  'V_GERM_LENGTH': None}

        # Find V positions
        if db['V_CALL']:
            # Query positions
            result['V_SEQ_START'] = int(record['V_SEQ_START'])
            result['V_SEQ_LENGTH'] = len(record['V_SEQ'].strip('.'))
            # Germline positions
            db['V_GERM_START_VDJ'] = 1
            db['V_GERM_LENGTH_VDJ'] = result['V_SEQ_LENGTH']

        return result

    def _parseDHit(record, db):
        """
        Parse D alignment information

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.
          db : database containing V alignment information.


        Returns:
          dict : database entries containing D call and alignment positions.
        """

        # D start position
        def _dstart():
            nb = [db['V_SEQ_START'],
                  db['V_SEQ_LENGTH'],
                  db['NP1_LENGTH']]
            return sum(int(i) for i in nb if i)

        # Default return
        result = {'D_SEQ_START': None,
                  'D_SEQ_LENGTH': None,
                  'D_GERM_START': None,
                  'D_GERM_LENGTH': None}

        if db['D_CALL']:
            # Query positions
            result['D_SEQ_START'] = _dstart()
            result['D_SEQ_LENGTH'] = len(record['D_SEQ'].strip('.'))
            # Germline positions
            result['D_GERM_START'] = len(record['D_SEQ']) - len(record['D_SEQ'].lstrip('.'))
            result['D_GERM_LENGTH'] = result['D_SEQ_LENGTH']

        return result

    @staticmethod
    def _parseJHit(record, db):
        """
        Parse J alignment information

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.
          db : database containing V and D alignment information.

        Returns:
          dict : database entries containing J call and alignment positions.
        """

        # J start position
        def _jstart():
            # J positions
            nb = [db['V_SEQ_START'],
                  db['V_SEQ_LENGTH'],
                  db['NP1_LENGTH'],
                  db['D_SEQ_LENGTH'],
                  db['NP2_LENGTH']]
            return sum(int(i) for i in nb if i)

        # Default return
        result = {'J_SEQ_START': None,
                  'J_SEQ_LENGTH': None,
                  'J_GERM_START': None,
                  'J_GERM_LENGTH': None}

        # Find J region
        if db['J_CALL']:
            # Query positions
            result['J_SEQ_START'] = _jstart()
            result['J_SEQ_LENGTH'] = len(record['J_SEQ'].strip('.'))
            # Germline positions
            result['J_GERM_START'] = len(record['J_SEQ']) - len(record['J_SEQ'].lstrip('.'))
            result['J_GERM_LENGTH'] = result['J_SEQ_LENGTH']

        return result

    @staticmethod
    def _assembleVDJ(record, db):
        """
        Build full length V(D)J sequence

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.
          db : database containing V and D alignment information.

        Returns:
          dict : database entries containing the full length V(D)J sequence.
        """
        segments = [record['V_SEQ'].strip('.') if db['V_CALL'] else '',
                    record['NP1_SEQ'] if db['NP1_LENGTH'] else '',
                    record['D_SEQ'].strip('.') if db['D_CALL'] else '',
                    record['NP2_SEQ'] if db['NP2_LENGTH'] else '',
                    record['J_SEQ'].strip('.') if db['J_CALL'] else '']

        return {'SEQUENCE_VDJ': ''.join(segments)}

    @staticmethod
    def _parseScores(record):
        """
        Parse alignment scores

        Arguments:
          record : dictionary containing a single row from the iHMMune-Align ouptut.

        Returns:
          dict : database entries for alignment scores.
        """
        result = {}
        try:
            result['HMM_SCORE'] = float(record['HMM_SCORE'])
        except (TypeError, ValueError):
            result['HMM_SCORE'] = None

        return result

    def parseRecord(self, record):
        """
        Parses a single row from each IMTG file.

        Arguments:
          record : dictionary containing one row of iHMMune-Align file.

        Returns:
          dict : database entry for the row.
        """
        # Extract query ID and sequence
        query = record['SEQUENCE_ID']
        db = {'SEQUENCE_ID': query,
              'SEQUENCE_INPUT': str(self.seq_dict[query].seq)}

        # Check for valid alignment
        if not record['V_CALL'] or \
                record['V_CALL'].startswith('NA - ') or \
                record['V_CALL'].startswith('State path'):
            db['FUNCTIONAL'] = None
            db['V_CALL'] = None
            db['D_CALL'] = None
            db['J_CALL'] = None
            return db

        # Parse record
        db.update(IHMMuneReader._parseFunctionality(record))
        db.update(IHMMuneReader._parseGenes(record))
        db.update(IHMMuneReader._parseNPHit(record))
        db.update(IHMMuneReader._parseVHit(record, db))
        db.update(IHMMuneReader._parseDHit(record, db))
        db.update(IHMMuneReader._parseJHit(record, db))
        db.update(IHMMuneReader._assembleVDJ(record, db))

        # Create IMGT-gapped sequence
        if 'V_CALL' in db and db['V_CALL'] and \
                'SEQUENCE_VDJ' in db and db['SEQUENCE_VDJ']:
            imgt_dict = gapV(db['SEQUENCE_VDJ'],
                             v_germ_start=db['V_GERM_START_VDJ'],
                             v_germ_length=db['V_GERM_LENGTH_VDJ'],
                             v_call=db['V_CALL'],
                             references=self.repo_dict,
                             asis_calls=self.asis_calls)
            db.update(imgt_dict)

        # Infer IMGT junction
        if ('J_CALL' in db and db['J_CALL']) and \
                ('SEQUENCE_IMGT' in db and db['SEQUENCE_IMGT']):
            junc_dict = inferJunction(db['SEQUENCE_IMGT'],
                                      j_germ_start=db['J_GERM_START'],
                                      j_germ_length=db['J_GERM_LENGTH'],
                                      j_call=db['J_CALL'],
                                      references=self.repo_dict,
                                      asis_calls=self.asis_calls)
            db.update(junc_dict)

        # Overall alignment score
        db.update(IHMMuneReader._parseScores(record))

        # FWR and CDR regions
        db.update(getRegions(db.get('SEQUENCE_IMGT', None), db.get('JUNCTION_LENGTH', None)))
        
        return db

    def __iter__(self):
        """
        Iterator initializer.

        Returns:
          changeo.Parsers.IHMMuneReader
        """
        return self

    def __next__(self):
        """
        Next method.

        Returns:
          changeo.Receptor.Receptor : parsed IMGT/HighV-QUEST result as an Receptor (receptor=True) or dictionary (receptor=False).
        """
        # Get next set of records from dictionary readers
        try:
            record = None
            while not record:
                record = next(self.records)
        except StopIteration:
            raise StopIteration

        db = self.parseRecord(record)

        if self.receptor:
            return Receptor(db)
        else:
            return db


def gapV(seq, v_germ_start, v_germ_length, v_call, references, asis_calls=False):
    """
    Construction IMGT-gapped V segment sequences.

    Arguments:
      seq (str): V(D)J sequence alignment (SEQUENCE_VDJ).
      v_germ_start (int): start position V segment alignment in the germline (V_GERM_START_VDJ).
      v_germ_length (int): length of the V segment alignment against the germline (V_GERM_LENGTH_VDJ).
      v_call (str): V segment allele assignment (V_CALL).
      references (dict): dictionary of IMGT-gapped reference sequences.
      asis_calls (bool): if True do not parse v_call for allele names and just split by comma.

    Returns:
      dict : dictionary containing IMGT-gapped query sequences and germline positions.
    """
    # Initialize return object
    imgt_dict = {'SEQUENCE_IMGT': None,
                 'V_GERM_START_IMGT': None,
                 'V_GERM_LENGTH_IMGT': None}

    # Initialize imgt gapped sequence
    seq_imgt = '.' * (int(v_germ_length) - 1) + seq

    # Extract first V call
    if not asis_calls:
        vgene = parseAllele(v_call, v_allele_regex, 'first')
    else:
        vgene = v_call.split(',')[0]

    # Find gapped germline V segment
    if vgene in references:
        vgap = references[vgene]
        # Iterate over gaps in the germline segment
        gaps = re.finditer(r'\.', vgap)
        gapcount = int(v_germ_start) - 1
        for gap in gaps:
            i = gap.start()
            # Break if gap begins after V region
            if i >= v_germ_length + gapcount:
                break
            # Insert gap into IMGT sequence
            seq_imgt = seq_imgt[:i] + '.' + seq_imgt[i:]
            # Update gap counter
            gapcount += 1

        imgt_dict['SEQUENCE_IMGT'] = seq_imgt
        # Update IMGT positioning information for V
        imgt_dict['V_GERM_START_IMGT'] = 1
        imgt_dict['V_GERM_LENGTH_IMGT'] = v_germ_length + gapcount
    else:
        sys.stderr.write('WARNING: %s was not found in the germline repository. IMGT-gapped sequence cannot be determined.\n' \
                         % vgene)

    return imgt_dict


def inferJunction(seq, j_germ_start, j_germ_length, j_call, references, asis_calls=False):
    """
    Identify junction region by IMGT definition.

    Arguments:
      seq (str): IMGT-gapped V(D)J sequence alignment (SEQUENCE_IMGT).
      j_germ_start (int): start position J segment alignment in the germline (J_GERM_START).
      j_germ_length (int): length of the J segment alignment against the germline (J_GERM_LENGTH).
      j_call (str): J segment allele assignment (J_CALL).
      references (dict): dictionary of IMGT-gapped reference sequences.
      asis_calls (bool): if True do not parse V_CALL for allele names and just split by comma.

    Returns:
      dict : dictionary containing junction sequence, translation and length.
    """
    junc_dict = {'JUNCTION': None,
                 'JUNCTION_AA': None,
                 'JUNCTION_LENGTH': None}

    # Find germline J segment
    if not asis_calls:
        jgene = parseAllele(j_call, j_allele_regex, 'first')
    else:
        jgene = j_call.split(',')[0]
    jgerm = references.get(jgene, None)

    if jgerm is not None:
        # Look for (F|W)GXG amino acid motif in germline nucleotide sequence
        motif = re.search(r'T(TT|TC|GG)GG[ACGT]{4}GG[AGCT]', jgerm)

        # Define junction end position
        seq_len = len(seq)
        if motif:
            j_start = seq_len - j_germ_length
            motif_pos = max(motif.start() - j_germ_start + 1, -1)
            junc_end = j_start + motif_pos + 3
        else:
            junc_end = seq_len

        # Extract junction
        junc_dict['JUNCTION'] = seq[309:junc_end]
        junc_len = len(junc_dict['JUNCTION'])
        junc_dict['JUNCTION_LENGTH'] = junc_len

        # Translation
        junc_tmp = junc_dict['JUNCTION'].replace('-', 'N').replace('.', 'N')
        if junc_len % 3 > 0:  junc_tmp = junc_tmp[:junc_len - junc_len % 3]
        junc_dict['JUNCTION_AA'] = str(Seq(junc_tmp).translate())

    return junc_dict


def getRegions(seq, junction_length):
    """
    Identify FWR and CDR regions by IMGT definition.

    Arguments:
      seq : IMGT-gapped sequence.
      junction_length : length of the junction region in nucleotides.

    Returns:
      dict : dictionary of FWR and CDR sequences.
    """
    region_dict = {'FWR1_IMGT': None,
                   'FWR2_IMGT': None,
                   'FWR3_IMGT': None,
                   'FWR4_IMGT': None,
                   'CDR1_IMGT': None,
                   'CDR2_IMGT': None,
                   'CDR3_IMGT': None}
    try:
        seq_len = len(seq)
        region_dict['FWR1_IMGT'] = seq[0:min(78, seq_len)]
    except (KeyError, IndexError, TypeError):
        return region_dict

    try: region_dict['CDR1_IMGT'] = seq[78:min(114, seq_len)]
    except (IndexError): return region_dict

    try: region_dict['FWR2_IMGT'] = seq[114:min(165, seq_len)]
    except (IndexError): return region_dict

    try: region_dict['CDR2_IMGT'] = seq[165:min(195, seq_len)]
    except (IndexError): return region_dict

    try: region_dict['FWR3_IMGT'] = seq[195:min(312, seq_len)]
    except (IndexError): return region_dict

    try:
        # CDR3
        cdr3_end = 306 + junction_length
        region_dict['CDR3_IMGT'] = seq[312:cdr3_end]
        # FWR4
        region_dict['FWR4_IMGT'] = seq[cdr3_end:]
    except (KeyError, IndexError, TypeError):
        return region_dict

    return region_dict


def readGermlines(repo, asis=False):
    """
    Parses germline repositories

    Arguments:
      repo : list of strings specifying directories and/or files from which to read germline records.
      asis : if True use sequence ID as record name and do not parse headers for allele names.

    Returns:
      dict : Dictionary of {allele: sequence} germlines
    """
    repo_files = []
    # Iterate over items passed to commandline
    for r in repo:
        # If directory, get fasta files from within
        if os.path.isdir(r):
            repo_files.extend([os.path.join(r, f) for f in os.listdir(r) \
                          if getFileType(f) == 'fasta'])
        # If file, make sure file is fasta
        if os.path.isfile(r) and getFileType(r) == 'fasta':
            repo_files.extend([r])

    # Catch instances where no valid fasta files were passed in
    if len(repo_files) < 1:
        sys.exit('\nERROR: No valid germline fasta files (.fasta, .fna, .fa) were found in %s' \
                 % ','.join(repo))

    references = {}
    for file_name in repo_files:
        with open(file_name, 'rU') as file_handle:
            germlines = SeqIO.parse(file_handle, 'fasta')
            for g in germlines:
                germ_key = parseAllele(g.description, allele_regex, 'first') if not asis else g.id
                references[germ_key] = str(g.seq).upper()

    return references


def extractIMGT(imgt_output):
    """
    Extract necessary files from IMGT/HighV-QUEST results.

    Arguments:
      imgt_output : zipped file or unzipped folder output by IMGT/HighV-QUEST.

    Returns:
      tuple : (temporary directory handle, dictionary with names of extracted IMGT files).
    """
    # Map of IMGT file names
    imgt_names = ('1_Summary', '2_IMGT-gapped', '3_Nt-sequences', '6_Junction')
    imgt_keys = ('summary', 'gapped', 'ntseq', 'junction')

    # Open temporary directory and intialize return dictionary
    temp_dir = TemporaryDirectory()

    # Zip input
    if zipfile.is_zipfile(imgt_output):
        imgt_zip = zipfile.ZipFile(imgt_output, 'r')
        # Extract required files
        imgt_files = sorted([n for n in imgt_zip.namelist() \
                             if os.path.basename(n).startswith(imgt_names)])
        imgt_zip.extractall(temp_dir.name, imgt_files)
        # Define file dictionary
        imgt_dict = {k: os.path.join(temp_dir.name, f) for k, f in zip_longest(imgt_keys, imgt_files)}
    # Folder input
    elif os.path.isdir(imgt_output):
        folder_files = []
        for root, dirs, files in os.walk(imgt_output):
            folder_files.extend([os.path.join(os.path.abspath(root), f) for f in files])
        # Define file dictionary
        imgt_files = sorted([n for n in folder_files \
                             if os.path.basename(n).startswith(imgt_names)])
        imgt_dict = {k: f for k, f in zip_longest(imgt_keys, imgt_files)}
    # Tarball input
    elif tarfile.is_tarfile(imgt_output):
        imgt_tar = tarfile.open(imgt_output, 'r')
        # Extract required files
        imgt_files = sorted([n for n in imgt_tar.getnames() \
                             if os.path.basename(n).startswith(imgt_names)])
        imgt_tar.extractall(temp_dir.name, [imgt_tar.getmember(n) for n in imgt_files])
        # Define file dictionary
        imgt_dict = {k: os.path.join(temp_dir.name, f) for k, f in zip_longest(imgt_keys, imgt_files)}
    else:
        sys.exit('ERROR: Unsupported IGMT output file. Must be either a zipped file (.zip), LZMA compressed tarfile (.txz) or a folder.')

    # Check extraction for errors
    if len(imgt_dict) != len(imgt_names):
        sys.exit('ERROR: Extra files or missing necessary file IMGT output %s.' % imgt_output)

    return temp_dir, imgt_dict


def countDbFile(file):
    """
    Counts the records in database files

    Arguments:
      file : tab-delimited database file.

    Returns:
      int : count of records in the database file.
    """
    # Count records and check file
    try:
        with open(file, 'rt') as db_handle:
            db_records = csv.reader(db_handle, dialect='excel-tab')
            for i, __ in enumerate(db_records):  pass
        db_count = i
    except IOError:
        sys.exit('ERROR:  File %s cannot be read' % file)
    except:
        sys.exit('ERROR:  File %s is invalid' % file)
    else:
        if db_count == 0:  sys.exit('ERROR:  File %s is empty' % file)

    return db_count


def getDbFields(file, add=None, exclude=None, reader=TSVReader):
    """
    Get field names from a db file

    Arguments:
      file : db file to pull base fields from.
      add : fields to append to the field set.
      exclude : fields to exclude from the field set.
      reader : reader class.

    Returns:
        list : list of field names
    """
    try:
        with open(file, 'rt') as handle:
            fields = reader(handle).fields
    except IOError:
        sys.exit('ERROR:  File %s cannot be read' % file)
    except:
        sys.exit('ERROR:  File %s is invalid' % file)

    # Add extra fields
    if add is not None:
        if not isinstance(add, list):  add = [add]
        fields.extend([f for f in add if f not in fields])
    # Remove unwanted fields
    if exclude is not None:
        if not isinstance(exclude, list):  exclude = [exclude]
        fields = [f for f in fields if f not in exclude]

    return fields


def getFileExt(filename):
    """
    Extract the extension from a file name

    Arguments:
      filename : file name

    Returns:
      str : file extension
    """
    file_type = os.path.splitext(filename)[1].lower().lstrip('.')

    return file_type