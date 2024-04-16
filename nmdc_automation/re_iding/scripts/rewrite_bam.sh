#!/bin/sh
#

IMG=biocontainers/samtools:1.3.1

if which samtools>/dev/null ; then
	in=$2
	out=$3
	old=$4
	new=$5
	echo "Rewriting $out"
	samtools view -h $in | sed "s/${old}/${new}/g" | \
          samtools view -hb -o $out
elif which shifter>/dev/null ; then 
	shifter --image=$IMG $0 $@
elif which docker>/dev/null ; then
	docker run --platform linux/amd64 --rm -v $0:/script --entrypoint /bin/bash $IMG /script $@
else
	echo "no container runtime"
        exit 1
fi

