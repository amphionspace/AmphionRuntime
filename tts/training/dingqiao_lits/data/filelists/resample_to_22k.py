import os
from multiprocessing import Pool, cpu_count

import librosa
import soundfile as sf
from tqdm import tqdm

input_txt = "/chenmingjie/xingwen/bn-en_Lits_22k/data/filelists/short_meta.txt"  # 改成你的txt路径
target_sr = 22050

# 原始路径前缀
prefix1 = "/chenmingjie/xingwen/dataset/Dataset/en/hi_fi_tts_v0/audio/9017_clean_wav_24k"
prefix2 = "/chenmingjie/xingwen/dataset/short_snippets/wavs"

# 输出路径前缀
out_prefix1 = "/chenmingjie/xingwen/dataset/Dataset/en/hi_fi_tts_v0/audio/9017_clean_wav_22k"
out_prefix2 = "/chenmingjie/xingwen/dataset/short_snippets/wavs22k"

# 并行进程数
num_workers = min(8, cpu_count())


def get_output_path(wav_path: str):
    if wav_path.startswith(prefix1):
        return wav_path.replace(prefix1, out_prefix1, 1)
    if wav_path.startswith(prefix2):
        return wav_path.replace(prefix2, out_prefix2, 1)
    return None


def process_one(wav_path: str):
    try:
        out_path = get_output_path(wav_path)
        if out_path is None:
            return f"跳过，未知路径前缀: {wav_path}"

        if os.path.exists(out_path):
            return None

        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        audio, sr = librosa.load(wav_path, sr=None, mono=False)

        if sr != target_sr:
            audio = librosa.resample(audio, orig_sr=sr, target_sr=target_sr)

        sf.write(out_path, audio, target_sr)
        return None

    except Exception as e:
        return f"失败: {wav_path} | {e}"


def load_wav_list(txt_path: str):
    wav_list = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split("|")
            if len(parts) not in (3, 5):
                print(f"格式异常，跳过: {line}")
                continue

            wav_path = parts[0].strip()
            wav_list.append(wav_path)

    return wav_list


def main():
    wav_list = load_wav_list(input_txt)
    print(f"总计待处理: {len(wav_list)}")

    errors = []

    with Pool(processes=num_workers) as pool:
        for result in tqdm(pool.imap_unordered(process_one, wav_list), total=len(wav_list)):
            if result is not None:
                errors.append(result)

    print(f"处理完成，错误数: {len(errors)}")

    if errors:
        err_file = "resample_errors.txt"
        with open(err_file, "w", encoding="utf-8") as f:
            for err in errors:
                f.write(err + "\n")
        print(f"错误日志已保存到: {err_file}")


if __name__ == "__main__":
    main()