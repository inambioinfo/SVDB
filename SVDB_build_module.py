import argparse
import readVCF
import SVDB_overlap_module
import subprocess
import sqlite3
import glob
import os


def fetch_index_variant(c,index):
    A='SELECT var ,chrA , chrB ,posA ,ci_A_lower ,ci_A_upper ,posB ,ci_B_lower ,ci_B_upper FROM SVDB WHERE idx == \'{}\' '.format(index)
    hits = c.execute(A)
    variant={}
    for hit in hits:
        variant["type"]=hit[0]
        variant["chrA"]=hit[1]
        variant["chrB"]=hit[2]
        variant["posA"]=int( hit[3] )
        variant["ci_A_start"]= int(hit[4])
        variant["ci_A_end"]= int(hit[5])
        variant["posB"]=int( hit[6] )
        variant["ci_B_start"]= int(hit[7])
        variant["ci_B_end"]= int(hit[8])
        
    return(variant)

def fetch_cluster_variant(c,index):
    A='SELECT posA, posB, sample FROM SVDB WHERE idx == \'{}\' '.format(index)
    hits = c.execute(A)
    variant={}
    for hit in hits:
        variant["posA"]=int( hit[0] )
        variant["posB"]=int( hit[1] )
        variant["sample_id"]=hit[2]
        
    return(variant)


def db_header():
    headerString="##fileformat=VCFv4.1\n";
    headerString+="##source=SVDB\n";
    headerString+="##ALT=<ID=DEL,Description=\"Deletion\">\n";
    headerString+="##ALT=<ID=DUP,Description=\"Duplication\">\n";
    headerString+="##ALT=<ID=INV,Description=\"Inversion\">\n";
    headerString+="##ALT=<ID=BND,Description=\"Break end\">\n";
    headerString+="##INFO=<ID=SVTYPE,Number=1,Type=String,Description=\"Type of structural variant\">\n";
    headerString+="##INFO=<ID=END,Number=1,Type=String,Description=\"End of an intra-chromosomal variant\">\n";
    headerString+="##INFO=<ID=OCC,Number=1,Type=Integer,Description=\"The number of occurances of the event in the database\">\n";
    headerString+="##INFO=<ID=NSAMPLES,Number=1,Type=Int,Description=\"the number of samples within the database\">\n";
    headerString+="##INFO=<ID=VARIANTS,Number=1,Type=Int,Description=\"a| separated list of the positions of the clustered variants\">\n";
    headerString+="##INFO=<ID=FRQ,Number=1,Type=Float,Description=\"the frequency of the vriant\">\n";
    headerString+="##INFO=<ID=SVLEN,Number=1,Type=Integer,Description=\"Difference in length between REF and ALT alleles\">\n"
    headerString+="##FORMAT=<ID=GT,Number=1,Type=String,Description=\"Genotype\">"
    return(headerString)


def vcf_line(cluster,id_tag,sample_IDs):
    info_field="SVTYPE={};".format(cluster[0]["type"])
    vcf_line=[]
    vcf_line.append( cluster[0]["chrA"] )
    vcf_line.append( str(cluster[0]["posA"]) )
    vcf_line.append( id_tag )
    vcf_line.append( "N" )
    if cluster[0]["chrA"] == cluster[0]["chrB"]:
        vcf_line.append( cluster[0]["type"] )
        info_field += "END={};SVLEN={};".format(cluster[0]["posB"],abs(cluster[0]["posA"]-cluster[0]["posB"]))
    else:
        vcf_line.append( "N[{}:{}[".format(cluster[0]["chrB"],cluster[0]["posB"]) )
        
        
    sample_set=set([])
    for variant in cluster[1]:
        sample_set.add(cluster[1][variant]["sample_id"])
    info_field += "NSAMPLES={};OCC={};FRQ={};".format(len(sample_IDs),len(sample_set),round(len(sample_set)/float(len(sample_IDs)) ,2))
    variant_field="VARIANTS="
    for variant in cluster[1]:
        variant_field +="|{}:{}:{}".format(cluster[1][variant]["sample_id"],cluster[1][variant]["posA"],cluster[1][variant]["posB"])
    info_field+=variant_field
    vcf_line.append( "." )
    vcf_line.append( "PASS" )
    vcf_line.append( info_field )
    zygosity_list={}
    for sample in sample_IDs:
        zygosity_list[sample]="0/0"
    
    for variant in cluster[1]:
        zygosity_list[cluster[1][variant]["sample_id"]]="./."
    format=[]
    for sample in zygosity_list:
        format.append(zygosity_list[sample])
    vcf_line.append("GT")
    vcf_line.append("\t".join(format))
    return( "\t".join(vcf_line) )

def populate_db(args):
    sample_IDs=[]
    conn = sqlite3.connect(args.db+".db")
    c = conn.cursor()
    tableListQuery = "SELECT name FROM sqlite_master WHERE type=\'table\'"
    c.execute(tableListQuery)
    tables = map(lambda t: t[0], c.fetchall())
    new_db = False
    
    
    
    idx=0;
    if not "SVDB" in tables:
        new_db = True
        A="CREATE TABLE SVDB (var TEXT,chrA TEXT, chrB TEXT,posA INT,ci_A_lower INT,ci_A_upper INT,posB INT,ci_B_lower INT,ci_B_upper INT, sample TEXT, idx INT)"
        c.execute(A) 
    else:
        A="DROP INDEX SV "
        c.execute(A)
        A="DROP INDEX IDX"
        c.execute(A)
        A="SELECT MAX(idx) FROM SVDB"
        number_of_variants=0
        for hit in c.execute(A):
            number_of_variants=int(hit[0])
        idx= 1+number_of_variants
    
    #populate the tables
    for vcf in args.files:
        sample_name=vcf.split("/")[-1]
        sample_name=sample_name.replace(".vcf","")
        sample_name=sample_name.replace(".","_")
        sample_IDs.append(sample_name)
        A='SELECT sample FROM SVDB WHERE sample == \'{}\' '.format(sample_name)
        hits=[]
        for hit in c.execute(A):
            hits.append(hit)
            
        if hits:
            continue        
        
        var =[]
        for line in open(vcf):
            if line.startswith("#"):
                continue
            chrA,posA,chrB,posB,event_type,INFO,FORMAT = readVCF.readVCFLine(line)
            ci_A_lower=0
            ci_A_upper=0
            ci_B_lower=0
            ci_B_upper=0
            if "CIPOS" in INFO:
                ci=INFO["CIPOS"].split(",")
                if len(ci) > 1:
                    ci_A_lower = abs(int(ci[0]))
                    ci_A_upper = abs(int(ci[1]))
                    ci_B_lower = abs(int(ci[0]))
                    ci_B_upper = abs(int(ci[1]))
                else:
                    ci_A_lower = abs(int(ci[0]))
                    ci_A_upper = abs(int(ci[0]))
                    ci_B_lower = abs(int(ci[0]))
                    ci_B_upper = abs(int(ci[0]))
            
            
            if "CIEND" in INFO:
                ci=INFO["CIEND"].split(",")
                if len(ci) > 1:
                    ci_B_lower = abs(int(ci[0]))
                    ci_B_upper = abs(int(ci[1]))
                else:
                    ci_B_lower = abs(int(ci[0]))
                    ci_B_upper = abs(int(ci[0]))
           
            
            var.append((event_type,chrA,chrB,posA,ci_A_lower,ci_A_upper,posB,ci_B_lower,ci_B_upper,sample_name,idx))
            idx += 1;
            #insert EVERYTHING into the database, the user may then query it in different ways(at least until the DB gets to large to function properly)
        c.executemany('INSERT INTO SVDB VALUES (?,?,?,?,?,?,?,?,?,?,?)',var)     
        

    A="CREATE INDEX SV ON SVDB (var,chrA, chrB, posA,posA,posB,posB)"
    c.execute(A)
    A="CREATE INDEX IDX ON SVDB (idx)"
    c.execute(A)
    #test query
    #A = "EXPLAIN QUERY PLAN SELECT * FROM SVDB WHERE var == \'DEL\' AND chrA == \'1\' AND chrB == \'1\' AND posA <= 1 AND posA >= 1 AND posB <= 1 AND posB >= 1"
    #print "query plan:"
    #for hit in c.execute(A):
    #    print hit
        
    conn.commit()
    conn.close()
    return(sample_IDs)

def expand_chain(chain,c,distance,overlap,ci):
    tested=set([])
    chain_data={}
    while not tested == chain:
        to_be_tested=chain-tested
        for index in to_be_tested:
            chain_data[index]=[]
            variant=fetch_index_variant(c,index)
            selection ="idx"
            if variant["chrA"] == variant["chrB"]:
                selection = "posA, posB, idx"
            if not ci:
                A='SELECT {} FROM SVDB WHERE var == \'{}\' AND chrA == \'{}\' AND chrB == \'{}\' AND posA <= {} AND posA >= {} AND posB <= {} AND posB >= {}'.format(selection,variant["type"],variant["chrA"],variant["chrB"],variant["posA"]+distance, variant["posA"] -distance,variant["posB"] + distance, variant["posB"]-distance)
                #print A
            else:
                A='SELECT idx FROM SVDB WHERE var == \'{}\' AND chrA == \'{}\' AND chrB == \'{}\' AND posA <= {} AND posA >= {} AND posB <= {} AND posB >= {}'.format(variant["type"],variant["chrA"],variant["chrB"],variant["posA"]+variant["ci_A_end"], variant["posA"] -variant["ci_A_start"],variant["posB"] + variant["ci_B_end"], variant["posB"] - variant["ci_B_start"])
            
            hits = c.execute(A)
            for hit in hits:
                if not ci and variant["chrA"] == variant["chrB"]:
                    var={}
                    var["posA"]=int( hit[0] )
                    var["posB"]=int( hit[1] )
                    var["index"]=int( hit[2] )
                    similar=SVDB_overlap_module.isSameVariation(variant["posA"],variant["posB"],var["posA"],var["posB"],overlap,distance)
                    if similar:
                        chain_data[index].append(var["index"])
                        chain.add( int( var["index"]) )
                    
                else:
                    chain_data[index].append(int( hit[0] ))
                    chain.add( int( hit[0] ) )

            tested.add(index)             
            #print"{} {} {} {} {}".format(variant["type"],variant["chrA"],variant["chrB"],variant["posA"],variant["posB"])
    return([chain,chain_data])

def cluster(c,chain,chain_data,distance,overlap,ci):
    clusters=[]
    for index in sorted(chain_data, key=lambda index: len(chain_data[index]), reverse=True):
        if not chain:
            break
        if not index in chain:
            continue
            
        variant_dictionary={}
        for var in chain_data[index]:
            if var in chain:
                chain.remove(var)
            variant_dictionary[var]=fetch_cluster_variant(c,var)
        variant=fetch_index_variant(c,index)
        
        clusters.append( [variant,variant_dictionary] )      
    return(clusters)

def generate_chains(db,distance,overlap,ci,sample_IDs):

    #memory_db=sqlite3.connect(':memory:')
    f = open(db+".vcf",'a')
    conn = sqlite3.connect(db+".db")
    #db_dump="".join(line for line in conn.iterdump())
    #memory_db.executescript(db_dump)
    #conn.close
    #c = memory_db.cursor()
    c=conn.cursor()

    chains=[]
    A="SELECT MAX(idx) FROM SVDB"
    number_of_variants=0
    for hit in c.execute(A):
        number_of_variants=int(hit[0])

    variant_list=set( range(0,number_of_variants) )
    summed=0;
    i =1
    while variant_list:
        chain= set([ min(variant_list) ])
        #find similar variants
        chain, chain_data= expand_chain(chain,c,distance,overlap,ci)
        for index in chain:
            if index in variant_list:
                variant_list.remove(index)

        clusters=cluster(c,chain,chain_data,distance,overlap,ci)
        for clustered_variants in clusters:        
            f.write( vcf_line(clustered_variants,"cluster_{}".format(i),sample_IDs )+"\n")
            i += 1
            
    f.close()
    
def main(args):
    args.db=args.prefix
    if(args.files):
        sample_IDs = populate_db(args)
    elif(args.folder):
        vcf_folder = glob.glob(os.path.join(args.folder,"*.vcf"));
        test=[];
        args.files=vcf_folder
        sample_IDs = populate_db(args)
    f = open(args.db+".vcf",'w')
    f.write( db_header()+"\n")
    f.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t{}\n".format("\t".join(sample_IDs)))
    f.close()
    generate_chains(args.db,args.bnd_distance,args.overlap,args.ci,sample_IDs )
