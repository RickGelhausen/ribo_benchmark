def read_parameters(filename):
    with open(filename, "r") as f:
        rpkm, cov = f.readline().split(",")
    return rpkm, cov



rule parseDeepRibo:
    input:
        covS= "coverage/{condition}-{replicate}_cov_fwd.bedgraph",
        covAS= "coverage/{condition}-{replicate}_cov_rev.bedgraph",
        asiteS= "coverage/{condition}-{replicate}_asite_fwd.bedgraph",
        asiteAS= "coverage/{condition}-{replicate}_asite_rev.bedgraph",
        genome= rules.retrieveGenome.output,
        annotation= rules.retrieveAnnotation.output
    output:
        "deepribo/{condition}-{replicate}/data_list.csv"
    conda:
        "../envs/deepribo.yaml"
    threads: 1
    shell:
        """
        mkdir -p deepribo/{wildcards.condition}-{wildcards.replicate}/0/;
        mkdir -p deepribo/{wildcards.condition}-{wildcards.replicate}/1/;
        python tools/DeepRibo/src/DataParser.py {input.covS} {input.covAS} {input.asiteS} {input.asiteAS} {input.genome} deepribo/{wildcards.condition}-{wildcards.replicate} -g {input.annotation}
        """

rule parameterEstimation:
    input:
        "deepribo/{condition}-{replicate}/data_list.csv"
    output:
        "deepribo/{condition}-{replicate}/parameters.txt"
    conda:
        "../envs/estimation.yaml"
    threads: 1
    shell:
        "mkdir -p deepribo; Rscript ribo_benchmark/scripts/parameter_estimation.R -f {input} > {output}"


rule predictDeepRibo:
    input:
        model= "tools/DeepRibo/models/DeepRibo_model_v1.pt",
        data= "deepribo/{condition}-{replicate}/data_list.csv",
        parameter="deepribo/{condition}-{replicate}/parameters.txt"
    output:
        "deepribo/{condition}-{replicate}/predictions.csv"
    conda:
        "../envs/deepribo.yaml"
    threads: 10
    params:
        rpkm, cov = read_parameters({input.parameters})
    shell:
        """
        mkdir -p deepribo;
        python tools/DeepRibo/src/DeepRibo.py predict deepribo/ --pred_data {wildcards.condition}-{wildcards.replicate}/ -r {params.rpkm} -c {params.cov} --model {input.model} --dest {output} --num_workers {threads}
        """
