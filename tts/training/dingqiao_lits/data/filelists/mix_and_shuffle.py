import random

train_val_ratio = 0.9

# all_to_mix = [
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/LJSpeech.txt",
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-CN9000_resampled.txt",
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-EN1800_resampled.txt",
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-MIX2000_pinyin_with_arpa_resampled.txt"
# ]
# all_to_mix = [
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/LJSpeech.txt",
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/bn_priya.txt"
# ]

# Files that need random train/val splitting
# unsplit_files = [ # MANDARIN
#     "./before_mix/LJSpeech.txt",
#     "./before_mix/LJS_synth_all_arpa.txt", # single + short
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-CN9000.txt",
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-EN1800.txt",
#     "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/zh-female-MIX2000.txt"
# ]
# unsplit_files = [ # RUSSIAN
#     "./before_mix/LJSpeech.txt",
#     "./before_mix/LJS_synth_all_arpa.txt", # single + short
#     "./before_mix/RUSLAN_cleaned.txt"
# ]
unsplit_files = [ # ARABIC
    "./before_mix/LJSpeech.txt",
    "./before_mix/LJS_synth_all_arpa.txt", # single + short
    "/data1/xiaoqihezuo/hanxingwen/LITs/dingqiao_filelists/ar_layla_cleaned.txt"
]

# Files that are already split — keep their train/val assignment
presplit_train_files = [

]
presplit_val_files = [

]

# OUTPUT_NAME = "en-zh_mix24k_arpa_pinyin_LJPlus"
OUTPUT_NAME = "ar-en_mix24k"
PREFIX = "dingqiao_" # use `dingqiao_` to ignore private data
# OUTPUT_NAME = "en-ru_mix16k_arpa_LJPlus"
# PREFIX = ""

def read_lines(path):
    with open(path, "r") as f:
        return [line.strip() for line in f if line.strip()]


random.seed(42)

train_list = []
val_list = []

for path in unsplit_files:
    lines = read_lines(path)
    random.shuffle(lines)
    split = int(len(lines) * train_val_ratio)
    train_list += lines[:split]
    val_list += lines[split:]

for path in presplit_train_files:
    train_list += read_lines(path)

for path in presplit_val_files:
    val_list += read_lines(path)

random.shuffle(train_list)
random.shuffle(val_list)

with open(f"./{PREFIX}{OUTPUT_NAME}_training.txt", "w", encoding="utf-8") as f:
    for line in train_list:
        f.write(line + "\n")

with open(f"./{PREFIX}{OUTPUT_NAME}_validation.txt", "w", encoding="utf-8") as f:
    for line in val_list:
        f.write(line + "\n")

print("Train set size:", len(train_list))
print("Validation set size:", len(val_list))