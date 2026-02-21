#!/bin/bash
# this endpoint uses the nmdcda client credentials
input_file=$1
set -euo pipefail
colon=%3A
temp="https://api.microbiomedata.org/jobs/field:release"
while read line; do  
  echo -e "\n$line"
  id=${line/:/"$colon"}
  echo $id
  url=${temp/field/$id}
  echo $url
  curl -X 'POST' \
  "$url" \
  -H 'accept: application/json' \
  -H 'Authorization: Bearer [replace]' \
  -d ''
done <"$input_file" 