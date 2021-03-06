#!/bin/python3

import xml.etree.ElementTree as ET
import argparse
import json
import os
import tempfile
import hashlib

from colors import info, error, warning
from shutil import copyfile, move
from collections import defaultdict

import pprint

# NOTE: instead of root.getchildren() use list(root)
# NOTE: print with ET.dump(<root>)

SUPPORTED_FILETYPES = "xml".split()
OPERATION_KEYWORDS = "failure success".split()
TYPE_KEYWORDS = "request response notification".split()
REPORT_FILE_NAME = "report-rename.json"
FORBIDDEN_WORDS = "android".split()
GENERIC_PAYMENT_METHODS = "*:${payment method}:${payment-method}".split(":")
ERROR_REPORT_FILE_NAME = "errors.json"
ERRORS = {"errors": [], "noxml": []}


def contains_duplicates(container, include_none=False):
    if include_none == False:
        container = [x for x in container if x is not None]
    return len(container) != len(set(container))


def find_duplicates(new_files, old_files):
    duplicates = {}
    for new, old in zip(new_files, old_files):
        if duplicates.get(new) == None or not isinstance(duplicates[new], list):
            duplicates[new] = []
        duplicates[new].append(old)
    duplicates = dict(
        filter(lambda e: e[0] is not None and len(e[1]) > 1, duplicates.items()))
    return duplicates


def remove_namespace(root):
    """Take a root element and return the sanitized tree.
    Sanitized meaning without namespaces.
    """
    root.tag = root.tag[root.tag.find('}')+1:]
    for child in list(root):
        remove_namespace(child)


def read_mixed_file(file_name):
    """Takes a file with mixed content (e.g. plain text and xml).
    Returns a tuple containing the split contents.

    Splitting is determined by the first line to start with '<',
    i.e. the first tag.
    """
    with open(file_name, "r", encoding="utf8") as f:
        found_beginning = False
        header = []
        xml = []
        for line in f:
            if line.startswith("<"):
                found_beginning = True
            if found_beginning:
                xml.append(line.rstrip())
            else:
                header.append(line.rstrip())

    return ("\n".join(header), "\n".join(xml) if xml else None)


def process_file_name(file_name, header_dict=None, dry_run=False):
    """Take a file name and return the new adapted file name + possible header information.

    Return: (new_file_name, header_file_name)
    """
    extension = file_name.split(".")[-1]

    if not any(file_name.endswith(ext) for ext in SUPPORTED_FILETYPES):
        raise ValueError("Unsupported file extension: must be one of {}, but was {}".format(
            ",".join(SUPPORTED_FILETYPES), extension))

    # skip all forbidden names
    if any((keyword in file_name.lower()) for keyword in FORBIDDEN_WORDS):
        return None

    ###########################################################################
    # CAUTION: Request can occur twice, or Request/Response is mixed
    # (each occuring one time)
    ###########################################################################
    send_type = "unknown"
    for keyword in TYPE_KEYWORDS:
        if keyword in file_name.lower():
            send_type = keyword
            if keyword != "request":
                break

    # get whether the request is a success or failure example
    success_or_fail = ""
    for keyword in OPERATION_KEYWORDS:
        if keyword in file_name.lower():
            success_or_fail = keyword
            break

    folder = "/".join(file_name.split("/")[:-1])

    try:
        tree = ET.parse(file_name)
    except ET.ParseError as e:
        content = ""
        with open(file_name, "r", encoding="utf8") as f:
            content = f.read()
        if str(e).startswith("syntax error: line 1, column 0") and not content.startswith("<"):
            # handle mixed files (header and XML information)
            # split them
            raw_header, raw_xml = read_mixed_file(file_name)
            header_file_name = ".".join(
                [file_name.split(".")[0] + "_header", "txt"])

            ###################################################################
            # FILE DOES NOT CONTAIN ANY VALID XML
            # thus, move to header file
            ###################################################################
            if raw_xml is None:
                info("[*] File has no XML: {}".format(file_name))
                ERRORS['noxml'].append(
                    {"file": file_name, "new-name": header_file_name})
                move(file_name, header_file_name)
                header_dict[file_name] = {"header": {
                    "xml": file_name, "txt": header_file_name}}
                return None

            ###################################################################
            # FILE CONTAINS HEADER AND VALID XML
            # split file into XML and header
            ###################################################################
            with open(file_name, "w+", encoding="utf8") as xml_f:
                xml_f.write(raw_xml)
            new_xml_file_name = process_file_name(file_name)
            # header_file_name = "/".join([folder,
            #                              ".".join([new_xml_file_name.split(".")[0] + "_header",
            #                                        "txt"])])
            with open(header_file_name, "w+", encoding="utf8") as header_f:
                header_f.write(raw_header)
            header_dict[new_xml_file_name] = {"header": {
                "old": header_file_name, "new": new_xml_file_name.split(".")[0] + "_header.txt"}}
            info("[*] Split into header and XML: %s" % (file_name))
            return new_xml_file_name

        else:
            error("[E] File: {}".format(file_name))
            error("    {}".format(e))
            ERRORS["errors"].append({"filename": file_name, "error": str(e)})
            return None
    except:
        error("[E] File: {}".format(file_name))
        error("    {}".format(e))
        raise


    root = tree.getroot()
    remove_namespace(root)

    payment_method = "generic"
    transaction_type = "unknown"
    step = ""
    try:
        step = "payment method"
        payment_method = root.find('payment-methods/payment-method').get('name')
        step = "transaction type"
        transaction_type = root.find('transaction-type').text
    except AttributeError as e:
        warning("[?] No %s found for %s" % (step, file_name))
        return None

    new_base_name = "{}_{}_{}_{}".format(
        "generic" if payment_method in GENERIC_PAYMENT_METHODS else payment_method,
        transaction_type, send_type, success_or_fail)

    ###########################################################################
    # IMPROVE NAMING WITH ADDITIONAL FIELDS
    ###########################################################################
    cryptogram_type = root.find('cryptogram/cryptogram-type')
    if cryptogram_type is not None:
        new_base_name = "%s_%s" % (cryptogram_type.text, new_base_name)

    locale = root.find('locale')
    country = root.find('country')
    if locale is not None:
        new_base_name += "_%s" % (locale.text)
    if country is not None:
        new_base_name += "_%s" % (country.text)

    periodic_type = root.find('periodic/periodic-type')
    sequence_type = root.find('periodic/sequence-type')
    if periodic_type is not None:
        new_base_name += "_%s" % (periodic_type.text)
    if sequence_type is not None:
        new_base_name += "_%s" % (sequence_type.text)

    request_type = root.find('request-type')
    if request_type is not None:
        new_base_name += "_%s" % (request_type.text)

    parent_id = root.find('parent-transaction-id')
    if parent_id is not None and not parent_id.text.startswith('${'):
        new_base_name += "_%s" % (parent_id.text.split("-")[0])

    return "/".join([folder, ".".join([new_base_name, extension])]).replace(' ', '')


def main():
    parser = argparse.ArgumentParser(description="""Systematically rename sample files
    (e.g. xml or json). Errors are always reported and written to 'errors.json'.
    If duplicate file names are found after all collision avoidance methods have been used,
    the script will dump the collisions to 'name_conflict.json'.
    Supported file types: {}""".format(", ".join(SUPPORTED_FILETYPES)))
    parser.add_argument("file", metavar="FILE", nargs="*",
                        help="Input file (needs to be supported)")
    parser.add_argument("-n", "--no-delete", action="store_true",
                        default=False, help="Whether or not to delete the original file")
    parser.add_argument("-d", "--dry-run", action="store_true", default=False,
                        help="Dry run - don't actually change or delete any files")
    parser.add_argument("-r", "--report", action="store_true",
                        default=False, help="Print report to file instead of stdout")
    parser.add_argument("--no-id", action="store_true", default=False,
                        help="Do not append an incrementing ID to filenames in order to resolve name conflicts.")
    parser.add_argument("-i", "--input-list",
                        help="List of files to rename, in case passing files via\
                            the command line does not work (too many files)")
    args = parser.parse_args()
    if not (args.file or args.input_list):
        parser.error("Specify either FILE or --input-list")
    if args.file:
        files = args.file
    if args.input_list:
        print("[*] load files via {}".format(args.input_list))
        with open(args.input_list, "r", encoding="utf8") as f:
            files = [line.strip() for line in f]

    ###########################################################################
    # START PROCESSING
    ###########################################################################
    # exception dict is needed for splitting up files with header information
    header_dict = {}
    processed_files = [process_file_name(
        file, header_dict=header_dict, dry_run=args.dry_run)
        for file in files]

    ###########################################################################
    # CHECK FOR DUPLICATES AND PERFORM MEASURES TO ELIMENATE THEM
    ###########################################################################
    if contains_duplicates(processed_files):
        duplicates = find_duplicates(processed_files, files)
        # if nothing helps, hash the files and append first 5 digits to filename
        updated_processed_files = []
        for new, old in zip(processed_files, files):
            if new in duplicates.keys():
                with open(old, "r", encoding="utf-8") as f:
                    sha1hash = hashlib.sha1(f.read().encode()).hexdigest()
                    (base_name, extension) = new.split(".")
                    new_file_name = ".".join(
                        ["%s_%s" % (base_name, sha1hash[:6]), extension])
                    updated_processed_files.append(new_file_name)
            else:
                updated_processed_files.append(new)

        processed_files = updated_processed_files

    ###########################################################################
    # TERMINATE IF DUPLICATES PERSIST OR APPEND IDs (depending on flags)
    ###########################################################################
    if contains_duplicates(processed_files):
        duplicates = find_duplicates(processed_files, files)
        if args.no_id:
            with open("name_conflicts.json", "w+", encoding="utf8") as f:
                f.write(json.dumps(duplicates, indent=2))
            error("[!] Found %d conflicting files" % (len(duplicates.keys())))
            raise ValueError(
                "found duplicate filenames list of processed files")
        else:
            info("[*] appending IDs to avoid conflicts")
            occurences = defaultdict(lambda: 1)
            updated_processed_files = []
            for new, old in zip(processed_files, files):
                if new in duplicates.keys():
                    (base_name, extension) = new.split(".")
                    new_file_name = ".".join(
                        ["%s_%s" % (base_name, occurences[new]), extension])
                    updated_processed_files.append(new_file_name)
                    occurences[new] += 1
                else:
                    updated_processed_files.append(new)

        processed_files = updated_processed_files

    if contains_duplicates(processed_files):
        duplicates = find_duplicates(processed_files, files)
        with open("name_conflicts.json", "w+", encoding="utf8") as f:
            f.write(json.dumps(duplicates, indent=2))
        error("[!] Found %d conflicting files" % (len(duplicates.keys())))
        raise ValueError(
            "found duplicate filenames list of processed files")

    ###########################################################################
    # PROCESS RENAMES
    ###########################################################################
    report_dict = {"renames": [{"old": old, "new": new}
                               for old, new in zip(files, processed_files)
                               if new is not None and new != old],
                   "header": [x
                              for k in header_dict.keys()
                              for x in header_dict[k].values()
                              ]}

    ERRORS['renames'] = [{"old": old, "new": new}
                         for old, new in zip(files, processed_files)
                         if new is None]

    for entry in report_dict['renames']:
        if entry['new'] in header_dict.keys():
            entry['header'] = header_dict[entry['new']]['header']

    ###########################################################################
    # WRITE REPORTS
    ###########################################################################
    if args.report:
        with open(REPORT_FILE_NAME, "w+", encoding="utf8") as report_f:
            report_f.write(json.dumps(report_dict, indent=2))
    elif not args.dry_run:
        print(json.dumps(report_dict, indent=2))

    with open(ERROR_REPORT_FILE_NAME, "w+", encoding="utf8") as error_f:
        error_f.write(json.dumps(ERRORS, indent=2))

    if args.dry_run:
        if not args.dry_run:
            for old, new in zip(files, processed_files):
                print("{} -> {}".format(old, new))
        return

    ###########################################################################
    # APPLY CHANGES TO HDD
    ###########################################################################
    for old, new in zip(files, processed_files):
        if (new is None) or (old == new):
            continue
        if args.no_delete:
            copyfile(old, new)
        else:
            move(old, new)
    # headers
    for old, new in [(d['header']['old'], d['header']['new'])
                     for d in header_dict.values()
                     if d['header'].get('old') is not None and
                     d['header'].get('new') is not None]:
        info("[H] move %s to %s" % (old, new))
        if os.path.exists(old):
            move(old, new)


if __name__ == "__main__":
    main()
