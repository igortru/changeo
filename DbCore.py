#!/usr/bin/env python
"""
Core functions shared by Change-O modules
"""

__author__    = 'Jason Anthony Vander Heiden, Namita Gupta'
__copyright__ = 'Copyright 2014 Kleinstein Lab, Yale University. All rights reserved.'
__license__   = 'Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported'
__version__   = '0.4.0'
__date__      = '2015.03.30'

# Imports
import csv, os, re, sys
from collections import OrderedDict
from Bio.Seq import Seq
from Bio.Alphabet import IUPAC

# Core imports
from IgCore import getScoreDict, scoreDNA, scoreAA

# Defaults
default_repo = 'germlines'
default_allele_regex = re.compile(r"(IG[HLK][VDJ]\d+[-/\w]*[-\*][\.\w]+)")
    
    
class IgRecord:
    """
    A class defining a V(D)J germline sequence alignment
    """
    # Private variables
    _key_map = {'id': 'SEQUENCE_ID',
                'v_call': 'V_CALL',
                'v_call_geno': 'V_CALL_GENOTYPED',
                'd_call': 'D_CALL',
                'j_call': 'J_CALL',
                'seq_in': 'SEQUENCE_INPUT',
                'seq_vdj': 'SEQUENCE_VDJ',
                'seq_imgt': 'SEQUENCE_IMGT',
                'junction': 'JUNCTION',
                'functional': 'FUNCTIONAL', 
                'in_frame': 'IN_FRAME', 
                'stop': 'STOP', 
                'mutated_invariant': 'MUTATED_INVARIANT', 
                'indels': 'INDELS',
                'v_seq_start': 'V_SEQ_START',
                'v_seq_length': 'V_SEQ_LENGTH',
                'v_germ_start': 'V_GERM_START',
                'v_germ_length': 'V_GERM_LENGTH',
                'n1_length': 'N1_LENGTH',
                'd_seq_start': 'D_SEQ_START',
                'd_seq_length': 'D_SEQ_LENGTH',
                'd_germ_start': 'D_GERM_START',
                'd_germ_length': 'D_GERM_LENGTH',
                'n2_length': 'N2_LENGTH',
                'j_seq_start': 'J_SEQ_START',
                'j_seq_length': 'J_SEQ_LENGTH',
                'j_germ_start': 'J_GERM_START',
                'j_germ_length': 'J_GERM_LENGTH',
                'junction_length': 'JUNCTION_LENGTH'}
    
    _parse_map = {'id': '_identity',
                  'v_call': '_identity',
                  'v_call_geno': '_identity',
                  'd_call': '_identity',
                  'j_call': '_identity',
                  'seq_in': '_sequence',
                  'seq_vdj': '_sequence',
                  'seq_imgt': '_sequence',
                  'junction': '_sequence',
                  'functional': '_logical', 
                  'in_frame': '_logical', 
                  'stop': '_logical', 
                  'mutated_invariant': '_logical', 
                  'indels': '_logical',
                  'v_seq_start': '_integer',
                  'v_seq_length': '_integer',
                  'v_germ_start': '_integer',
                  'v_germ_length': '_integer',
                  'n1_length': '_integer',
                  'd_seq_start': '_integer',
                  'd_seq_length': '_integer',
                  'd_germ_start': '_integer',
                  'd_germ_length': '_integer',
                  'n2_length': '_integer',
                  'j_seq_start': '_integer',
                  'j_seq_length': '_integer',
                  'j_germ_start': '_integer',
                  'j_germ_length': '_integer',
                  'junction_length': '_integer'}

    _logical_parse = {'F':False, 'T':True, 'TRUE':True, 'FALSE':False, 'NA':None}
    _logical_deparse = {False:'F', True:'T', None:'NA'}

    # TODO: inclusion of TR (additional match group) caused issues in DefineClones; needs fixing.
    # Public variables
    #allele_regex = re.compile(r'((IG[HLK]|TR[ABGD])[VDJ]\d+[-/\w]*[-\*][\.\w]+)')
    #gene_regex = re.compile(r'((IG[HLK]|TR[ABGD])[VDJ]\d+[-/\w]*)')
    #family_regex = re.compile(r'((IG[HLK]|TR[ABGD])[VDJ]\d+)')
    allele_regex = re.compile(r'(IG[HLK][VDJ]\d+[-/\w]*[-\*][\.\w]+)')
    gene_regex = re.compile(r'(IG[HLK][VDJ]\d+[-/\w]*)')
    family_regex = re.compile(r'(IG[HLK][VDJ]\d+)')

    # Private methods
    @staticmethod    
    def _identity(v, deparse=False):
        return v

    @staticmethod
    def _logical(v, deparse=False):
        if not deparse:
            try:  return IgRecord._logical_parse[v]
            except:  return None
        else:
            try:  return IgRecord._logical_deparse[v]
            except:  return ''

    @staticmethod
    def _integer(v, deparse=False):
        if not deparse:
            try:  return int(v)
            except:  return None
        else:
            try:  return str(v)
            except:  return ''
            
    @staticmethod
    def _sequence(v, deparse=False):
        if not deparse:
            try:  return Seq(v, IUPAC.ambiguous_dna)
            except:  return None
        else:
            try:  return str(v)
            except:  return ''
    
    @staticmethod
    def _parseAllele(alleles, regex, action='first'):
        x = regex.findall(alleles)
        if action == 'first':
            return x[0] if x else None
        elif action == 'set':
            return tuple(sorted(set(x))) if x else None
        elif action == 'list':
            return tuple(sorted(x)) if x else None
        else:
            return None

    # Initializer
    def __init__(self, row, genotyped=True):
        required_keys = ('id',)
        optional_keys = (x for x in IgRecord._parse_map if x not in required_keys)
        
        # Not ideal. Will place V_CALL_GENOTYPED in annotations
        if not genotyped and 'v_call_geno' in optional_keys:
            del optional_keys['v_call_geno']
            
        try:
            for k in required_keys:
                f = getattr(IgRecord, IgRecord._parse_map[k])
                setattr(self, k, f(row.pop(IgRecord._key_map[k])))
        except:
            sys.exit('ERROR:  Input must contain valid %s values' \
                     % ','.join([IgRecord._key_map[k] for k in required_keys]))

        # Defined optional logical values
        for k in optional_keys:
            f = getattr(IgRecord, IgRecord._parse_map[k])
            setattr(self, k, f(row.pop(IgRecord._key_map[k], None)))
            
        # Add remaining elements as annotations dictionary
        self.annotations = row
    
    # Return a dictionary of the namespace
    def toDict(self):
        d = {}
        n = self.__dict__
        for k, v in n.iteritems():
            if k == 'annotations':
                d.update({i.upper():j for i, j in n['annotations'].iteritems()})
            else:
                f = getattr(IgRecord, IgRecord._parse_map[k])
                d[IgRecord._key_map[k]] = f(v, deparse=True)
        return d
    
    # Allele, gene and family getter functions
    def getVAllele(self, action='first'):
        # NOTE: Can't distinguish empty value ("") from missing field (no column)
        x = self.v_call_geno if self.v_call_geno is not None else self.v_call
        return IgRecord._parseAllele(x, self.allele_regex, action)

    def getDAllele(self, action='first'):
        return IgRecord._parseAllele(self.d_call, self.allele_regex, action)

    def getJAllele(self, action='first'):
        return IgRecord._parseAllele(self.j_call, self.allele_regex, action)
    
    def getVGene(self, action='first'):
        return IgRecord._parseAllele(self.v_call, self.gene_regex, action)

    def getDGene(self, action='first'):
        return IgRecord._parseAllele(self.d_call, self.gene_regex, action)

    def getJGene(self, action='first'):
        return IgRecord._parseAllele(self.j_call, self.gene_regex, action)
    
    def getVFamily(self, action='first'):
        return IgRecord._parseAllele(self.v_call, self.family_regex, action)

    def getDFamily(self, action='first'):
        return IgRecord._parseAllele(self.d_call, self.family_regex, action)

    def getJFamily(self, action='first'):
        return IgRecord._parseAllele(self.j_call, self.family_regex, action)


class DbData:
    """
    A class defining IgRecord data objects for worker processes
    """
    # Instantiation
    def __init__(self, key, records):
        self.id = key
        self.data = records
        self.valid = (key is not None and records is not None)

    # Boolean evaluation
    def __nonzero__(self):
        return self.valid

    # Length evaluation
    def __len__(self):
        if isinstance(self.data, IgRecord):
            return 1
        elif self.data is None:
            return 0
        else:
            return len(self.data)


class DbResult:
    """
    A class defining IgRecord result objects for collector processes
    """
    # Instantiation
    def __init__(self, key, records):
        self.id = key
        self.data = records
        self.results = None
        self.valid = False
        self.log = OrderedDict([('ID', key)])
        #if isinstance(values, list):
        #    for v in values:  setattr(self, v, None)
        #else:
        #    setattr(self, values, None)

    # Boolean evaluation
    def __nonzero__(self):
        return self.valid

    # Length evaluation
    def __len__(self):
        if isinstance(self.results, IgRecord):
            return 1
        elif self.data is None:
            return 0
        else:
            return len(self.results)


# TODO:  Change to require output fields rather than in_file?
def getDbWriter(out_handle, in_file=None, add_fields=None, exclude_fields=None):
    """
    Opens a writer object for an output database file
    
    Arguments: 
    out_handle = the file handle to write to
    in_file = the input filename to determine output fields from;
              if None do not define output fields from input file
    add_fields = a list of fields added to the writer not present in the in_file;
                 if None do not add fields
    exclude_fields = a list of fields in the in_file excluded from the writer;
                     if None do not exclude fields
    
    Returns:
    a writer object
    """
    # Get output field names from input file
    if in_file is not None:
        fields = (readDbFile(in_file, ig=False)).fieldnames
    else:
        fields = []
    # Add extra fields
    if add_fields is not None:
        if not isinstance(add_fields, list):  add_fields = [add_fields]
        fields.extend([f for f in add_fields if f not in fields])
    # Remove unwanted fields
    if exclude_fields is not None:
        if not isinstance(exclude_fields, list):  exclude_fields = [exclude_fields]
        fields = [f for f in fields if f not in exclude_fields]

    # Create writer
    try:
        # >>> THIS NEEDS TO BE FIXED, extrasaction='ignore' IS A WORKAROUND FOR ADDITIONS TO IgRecord
        db_writer = csv.DictWriter(out_handle, fieldnames=fields, dialect='excel-tab', extrasaction='ignore')
        db_writer.writeheader()
    except:
        sys.exit('ERROR:  File %s cannot be written' % out_handle.name)

    return db_writer


# TODO:  Need to close db_handle?
def readDbFile(db_file, ig=True):
    """
    Reads database files

    Arguments: 
    db_file = a tab delimited database file
    ig = if True convert fields to an IgRecord
    
    Returns: 
    a database record iterator
    """
    # Read and check file
    try:
        db_handle = open(db_file, 'rb')
        db_reader = csv.DictReader(db_handle, dialect='excel-tab')
        if ig:  
            db_iter = (IgRecord(r) for r in db_reader)
        else:  
            db_iter = db_reader
    except IOError:
        sys.exit('ERROR:  File %s cannot be read' % db_file)
    except:
        sys.exit('ERROR:  File %s is invalid' % db_file)
    
    return db_iter


def countDbFile(db_file):
    """
    Counts the records in database files

    Arguments: 
    db_file = a tab delimited database file

    Returns: 
    the count of records in the database file
    """
    # Count records and check file
    try:
        with open(db_file) as db_handle:
            db_records = csv.reader(db_handle, dialect='excel-tab') 
            for i, __ in enumerate(db_records):  pass
        db_count = i
    except IOError:
        sys.exit('ERROR:  File %s cannot be read' % db_file)
    except:
        sys.exit('ERROR:  File %s is invalid' % db_file)
    else:
        if db_count == 0:  sys.exit('ERROR:  File %s is empty' % db_file)
        
    return db_count


def getDistMat(mat=None, n_score=0, gap_score=0, alphabet='dna'):
    """
    Generates a distance matrix

    Arguments:
    mat = input distance matrix to extend to full alphabet;
          if unspecified, creates Hamming distance matrix that incorporates IUPAC equivalencies
    n_score = score for all matches against an N character
    gap_score = score for all matches against a [-, .] character
    alphabet = the type of score dictionary to generate;
               one of [dna, aa] for DNA and amino acid characters

    Returns:
    a distance matrix (pandas DataFrame)
    """
    if alphabet=='dna':
        IUPAC_chars = list('-.ACGTRYSWKMBDHVN')
        n = 'N'
        score_func = scoreDNA
    elif alphabet=='aa':
        IUPAC_chars = list('-.*ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        n = 'X'
        score_func = scoreAA
    else:
        sys.stderr.write('ERROR:  The alphabet %s is not a recognized type.\n' % alphabet)

    # Default matrix to inf
    dist_mat = pd.DataFrame(float('inf'), index=IUPAC_chars, columns=IUPAC_chars, dtype=float)
    # Set gap score
    for c in '-.':
        dist_mat.loc[c] = dist_mat.loc[:,c] = gap_score
    # Set n score
    dist_mat.loc[n] = dist_mat.loc[:,n] = n_score
    # Fill in provided distances from input matrix
    if mat is not None:
        for i,j in product(mat.index, mat.columns):
            dist_mat.loc[i,j] = mat.loc[i,j]
    # If no input matrix, create IUPAC-defined Hamming distance
    else:
        for i,j in product(dist_mat.index, dist_mat.columns):
            dist_mat.loc[i,j] = 1 - score_func(i, j, n_score=1-n_score, gap_score=1-gap_score)

    return dist_mat


if __name__ == '__main__':
    """
    Print module information
    """
    print 'Version: %s %s %s' % (os.path.basename(__file__), __version__, __date__)
    print 'Location: %s' % os.path.dirname(os.path.realpath(__file__))
    #print 'Parent Dir: %s' % path.join(path.dirname(path.realpath(__file__)), path.pardir)

