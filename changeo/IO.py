"""
File I/O and logging functions
"""
# Info
__author__ = 'Namita Gupta, Jason Anthony Vander Heiden'
from changeo import __version__, __date__

# Imports
import csv
import os
import sys
import tarfile
import zipfile
from itertools import zip_longest
from tempfile import TemporaryDirectory
from Bio import SeqIO

# Presto and changeo imports
from changeo.Defaults import default_csv_size
from changeo.Receptor import parseAllele, allele_regex
from presto.IO import getFileType

# System settings
csv.field_size_limit(default_csv_size)


def readRepo(repo):
    """
    Parses germline repositories

    Arguments:
      repo : String list of directories and/or files
             from which to read germline records

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

    repo_dict = {}
    for file_name in repo_files:
        with open(file_name, 'rU') as file_handle:
            germlines = SeqIO.parse(file_handle, 'fasta')
            for g in germlines:
                germ_key = parseAllele(g.description, allele_regex, 'list')
                repo_dict[germ_key] = str(g.seq).upper()

    return repo_dict


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
        sys.exit('ERROR:  File %s cannot be read' % db_file)
    except:
        sys.exit('ERROR:  File %s is invalid' % db_file)
    else:
        if db_count == 0:  sys.exit('ERROR:  File %s is empty' % db_file)

    return db_count


def getDbFields(file, add=None, exclude=None):
    """
    Get field names from a db file

    Arguments:
      file : db file to pull base fields from.
      add : fields to append to the field set.
      exclude : fields to exclude from the field set.

    Returns:
        list : list of field names
    """
    try:
        with open(file, 'rt') as handle:
            reader = csv.DictReader(handle, dialect='excel-tab')
            fields = [n.strip().upper() for n in reader.fieldnames]
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
