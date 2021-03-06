#!/usr/bin/env python
import argparse
import re
import os, sys
import pandas as pd
import collections
from collections import Counter, OrderedDict
import csv

from Bio.Seq import Seq
from Bio import SeqIO
from Bio.Alphabet import generic_dna

class OrderedCounter(Counter, OrderedDict):
    pass

def calculate_rpkm(total_mapped, read_count, read_length):
    """
    calculate the rpkm
    """
    return float("%.2f" % ((read_count * 1000000000) / (total_mapped * read_length)))

def get_unique(in_list):
    seen = set()
    seen_add = seen.add
    return [x for x in in_list if not (x in seen or seen_add(x))]

def retrieve_column_information(attributes):
    """
    check for gff2/gff3 format and generate a list of information for the final tables
    [locus_tag, name, product, note]
    """

    if ";" in attributes and "=" in attributes:
        attribute_list = [x for x in re.split('[;=]', attributes) if x != ""]
    else:
        attribute_list = [x.replace("\"", "") for x in re.split('[; ]', attributes) if x != ""]

    if "ORF_type=;" in attributes:
        attribute_list.remove("ORF_type")

    if len(attribute_list) % 2 == 0:
        for i in range(len(attribute_list)):
            if i % 2 == 0:
                attribute_list[i] = attribute_list[i].lower()
    else:
        print(attributes)
        sys.exit("Attributes section of gtf/gff is wrongly formatted!")

    locus_tag = ""
    if "locus_tag" in attribute_list:
        locus_tag = attribute_list[attribute_list.index("locus_tag")+1]

    name = ""
    if "name" in attribute_list:
        name = attribute_list[attribute_list.index("name")+1]

    product = ""
    if "product" in attribute_list:
        product = attribute_list[attribute_list.index("product")+1]

    note = ""
    if "note" in attribute_list:
        note = attribute_list[attribute_list.index("note")+1]

    evidence = ""
    if "evidence" in attribute_list:
        evidence = attribute_list[attribute_list.index("evidence")+1]

    return [locus_tag, name, product, note, evidence]

def get_genome_information(genome, start, stop, strand):
    """
    retrieve the nucleotide sequence and amino acid sequence
    and the start and stop codons
    """
    if strand == "+":
        nucleotide_seq = genome[0][start:stop+1]
    else:
        nucleotide_seq = genome[1][start:stop+1][::-1]

    start_codon = nucleotide_seq[0:3]
    stop_codon = nucleotide_seq[-3:]

    coding_dna = Seq(nucleotide_seq, generic_dna)
    if len(coding_dna) % 3 != 0:
        aa_seq = ""
    else:
        aa_seq = str(coding_dna.translate(table=11,to_stop=True))
    return start_codon, stop_codon, nucleotide_seq, aa_seq

def excel_writer(args, data_frames, wildcards):
    """
    create an excel sheet out of a dictionary of data_frames
    correct the width of each column
    """
    header_only =  ["Note", "Aminoacid_seq", "Nucleotide_seq", "Start_codon", "Stop_codon", "Strand", "Codon_count"] + [card + "_rpkm" for card in wildcards]
    writer = pd.ExcelWriter(args.output, engine='xlsxwriter')
    for sheetname, df in data_frames.items():
        df.to_excel(writer, sheet_name=sheetname, index=False)
        worksheet = writer.sheets[sheetname]
        for idx, col in enumerate(df):
            series = df[col]
            if col in header_only:
                max_len = len(str(series.name)) + 2
            else:
                max_len = max(( series.astype(str).str.len().max(), len(str(series.name)) )) + 1
            print("Sheet: %s | col: %s | max_len: %s" % (sheetname, col, max_len))
            worksheet.set_column(idx, idx, max_len)
    writer.save()

def TE(ribo_count, rna_count):
    """
    calculate the translational efficiency for one entry
    """

    if ribo_count == 0 and rna_count == 0:
        return 0
    elif rna_count == 0:
        return ribo_count
    else:
        return ribo_count / rna_count

def calculate_TE(read_list, wildcards, conditions):
    """
    calculate the translational efficiency
    """
    read_dict = OrderedDict()
    for idx in range(len(wildcards)):
        method, condition, replicate = wildcards[idx].split("-")
        key = (method, condition)
        if key in read_dict:
            read_dict[key].append(read_list[idx])
        else:
            read_dict[key] = [read_list[idx]]

    TE_list = []
    for cond in conditions:
        if ("RNA", cond) not in read_dict:
            t_eff = [0 for idx in range(len(read_dict[("RIBO", cond)]))]
            if len(t_eff) > 1:
                t_eff.extend([sum(t_eff) / len(read_dict[("RIBO", cond)])])

            t_eff = [float("%.2f" % x) for x in t_eff]
            TE_list.extend(t_eff)
            continue

        if len(read_dict[("RIBO", cond)]) == len(read_dict[("RNA", cond)]):
            ribo_list = read_dict[("RIBO", cond)]
            rna_list = read_dict[("RNA", cond)]
            t_eff = [TE(ribo_list[idx],rna_list[idx]) for idx in range(len(ribo_list))]

            if len(t_eff) > 1:
                t_eff.extend([sum(t_eff) / len(ribo_list)])

            t_eff = [float("%.2f" % x) for x in t_eff]
            TE_list.extend(t_eff)
        else:
            TE_list.extend([0])

    return TE_list

def parse_orfs(args):
    # read the genome file
    genome_file = SeqIO.parse(args.genome, "fasta")
    genome_dict = dict()
    for entry in genome_file:
        genome_dict[str(entry.id)] = (str(entry.seq), str(entry.seq.complement()))

    # get the total mapped reads for each bam file
    total_mapped_dict = {}
    with open(args.total_mapped, "r") as f:
        total = f.readlines()

    wildcards = []
    for line in total:
        wildcard, reference_name, value = line.strip().split("\t")
        total_mapped_dict[(wildcard, reference_name)] = int(value)
        wildcards.append(wildcard)

    wildcards = get_unique(wildcards)

    TE_header = []
    for card in wildcards:
        if "RIBO" in card:
            TE_header.append(card.split("-")[1])

    counter = OrderedCounter(TE_header)
    TE_header = []
    for key, value in counter.items():
        for idx in range(value):
            TE_header.append("%s-%s" % (key,(idx+1)))
        if value > 1:
            TE_header.append("%s-avg" % key)

    conditions = []
    for card in wildcards:
        conditions.append(card.split("-")[1])

    conditions = get_unique(conditions)

    #read bed file
    read_df = pd.read_csv(args.reads, comment="#", header=None, sep="\t")

    # read gff file
    all_sheet = []
    rows_simple = []
    rows_complete = []

    header = ["Translated", "Genome", "Start", "Stop", "Strand", "Locus_tag", "Name", "Length", "Codon_count"] + [cond + "_TE" for cond in TE_header] + [card + "_rpkm" for card in wildcards] + ["Start_codon", "Stop_codon", "Nucleotide_seq", "Aminoacid_seq"]
    prefix_columns = len(read_df.columns) - len(wildcards)
    name_list = ["s%s" % str(x) for x in range(len(header))]
    nTuple = collections.namedtuple('Pandas', name_list)
    nTupleGFF = collections.namedtuple('Pandas', ["s0","s1","s2","s3","s4","s5","s6","s7","s8"])
    count = 0
    for row in read_df.itertuples(index=False, name='Pandas'):
        reference_name = getattr(row, "_0")
        source = getattr(row, "_1")
        feature = getattr(row, "_2")
        start = getattr(row, "_3")
        stop = getattr(row, "_4")
        strand = getattr(row, "_6")
        attributes = getattr(row, "_8")

        if feature.lower() not in ["cds", "pseudogene", "ncrna"]:
            continue

        start_codon, stop_codon, nucleotide_seq, aa_seq = get_genome_information(genome_dict[reference_name], start-1, stop-1, strand)
        column_info = retrieve_column_information(attributes)

        length = stop - start + 1
        codon_count = int(length / 3)

        read_list = [getattr(row, "_%s" %x) for x in range(prefix_columns,len(row))]
        rpkm_list = []
        for idx, val in enumerate(read_list):
            rpkm_list.append(calculate_rpkm(total_mapped_dict[(wildcards[idx], reference_name)], val, length))

        TE_list = calculate_TE(rpkm_list, wildcards, conditions)
        result = ["",reference_name, start, stop, strand, column_info[0], column_info[1], length, codon_count] + TE_list + rpkm_list + [start_codon, stop_codon, nucleotide_seq, aa_seq]

        result_simple = [reference_name, "generated", "feature", start, stop, ".", strand, ".", "ID=id%s;Name=%s;locus_tag=%s;old_name=%s" %(count, column_info[0], column_info[0], column_info[1])]
        result_complete = [reference_name, source, feature, start, stop, getattr(row, "_5"), strand, getattr(row, "_7"), attributes]
        count += 1
        all_sheet.append(nTuple(*result))
        rows_simple.append(nTupleGFF(*result_simple))
        rows_complete.append(nTupleGFF(*result_complete))

    all_df = pd.DataFrame.from_records(all_sheet, columns=[header[x] for x in range(len(header))])
    simple_df = pd.DataFrame.from_records(rows_simple, columns=[0,1,2,3,4,5,6,7,8])
    complete_df = pd.DataFrame.from_records(rows_complete, columns=[0,1,2,3,4,5,6,7,8])

    dataframe_dict = { "all" : all_df }
    with open(args.output_simple, "w") as f:
        f.write("##gff-version 3\n")
    with open(args.output_simple, "a") as f:
        simple_df.to_csv(f, header=None, sep="\t", index=False, quoting=csv.QUOTE_NONE)

    with open(args.output_complete, "w") as f:
        f.write("##gff-version 3\n")
    with open(args.output_complete, "a") as f:
        complete_df.to_csv(f, header=None, sep="\t", index=False, quoting=csv.QUOTE_NONE)

    excel_writer(args, dataframe_dict, wildcards)

def main():
    # store commandline args
    parser = argparse.ArgumentParser(description='create excel files containing: \
                                                id, start, stop, orflength, potential RBS, rpkm')
    parser.add_argument("-g", "--genome", action="store", dest="genome", required=True, help= "reference genome")
    parser.add_argument("-t", "--total_mapped_reads", action="store", dest="total_mapped", required=True\
                                                    , help= "file containing the total mapped reads for all alignment files.")
    parser.add_argument("-r", "--mapped_reads", action="store", dest="reads", required=True, help= "file containing the individual read counts")
    parser.add_argument("-o", "--xlsx", action="store", dest="output", required=True, help= "output xlsx file")
    parser.add_argument("--simple", action="store", dest="output_simple", required=True, help= "output gff simple file")
    parser.add_argument("--complete", action="store", dest="output_complete", required=True, help= "output gff complete file")
    args = parser.parse_args()

    parse_orfs(args)

if __name__ == '__main__':
    main()
