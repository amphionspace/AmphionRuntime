INPUT_FILE = "/chenmingjie/xingwen/en-zh_Lits_24k/data/filelists/en-zh_mix24k_validation.txt"

clean_lines = []
bad_wavs = [
    "/chenmingjie/xingwen/dataset/short_snippets/wavs/group_00716.wav",
    "/chenmingjie/xingwen/dataset/short_snippets/wavs/group_00245.wav"
]
with open(INPUT_FILE, "r") as f:
    for line in f:
        if bad_wavs[0] in line or bad_wavs[1] in line:
            continue
        clean_lines.append(line)

with open(INPUT_FILE, "w") as f:
    f.writelines(clean_lines)