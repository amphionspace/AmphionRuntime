from lits.text import text_to_sequence

# ARPA_FILELIST = "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/LJSpeech.txt"
# ARPA_FILELIST = "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-EN1800_resampled.txt"
# ARPA_FILELIST = "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-CN9000_resampled.txt"
# ARPA_FILELIST = "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-MIX2000_pinyin_with_arpa_resampled.txt"
ARPA_FILELIST = "/data1/xiaoqihezuo/hanxingwen/LITs/Multilingual_LITs/data/filelists/dingqiao_bn-en_mix24k_validation.txt"
bad = False
with open(ARPA_FILELIST, "r") as f:
    for idx, line in enumerate(f, start=1):
        wavname = line.strip().split("|")[0]
        text = line.strip().split("|")[-1]
        text_in_list = text.split()

        ids, cleaned = text_to_sequence(text, ['bn_en_mixed_cleaners'])
        if 2 in ids:
            print(f"Warning! Found sentence with unknown token in wav: {wavname}!")
            # print(f"Bad ids: {ids}")
            for idx2, id_item in enumerate(ids):
                if id_item == 2:
                    # print(f"Bad token at position {idx2}: {text_in_list[idx2]}")
                    print(cleaned)
                    exit()
            bad = True

if not bad:
    print("Alright.")
