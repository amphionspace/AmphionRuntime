import datetime as dt
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from tqdm.auto import tqdm
import argparse
import time
import traceback
import re
import unicodedata

from lits.models.lits import LITS
from lits.text import text_to_sequence
from lits.utils.utils import intersperse
from vocos.vocoder import load_vocos_vocoder

REPO_ROOT = Path(__file__).resolve().parent
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

parser = argparse.ArgumentParser()
parser.add_argument(
    '--model_lang',
    type=str,
    default='en-zh-dict',
    choices=['en-zh', 'en-zh-dict', 'ar-en', 'bn-en', 'en-ru', 'ar-en-dict'],
    help='Model language pair; en-zh-dict = hanzi lexicon + English CMUdict G2P',
)
parser.add_argument('--checkpoint', type=str, required=True, help='LITs checkpoint path')
parser.add_argument('--input_txt', type=str, required=True, help='Input txt file (each line: wav_path|text or wav_path|spk_id|text)')
parser.add_argument('--output_dir', type=str, required=True, help='Output audio folder')
parser.add_argument('--output_txt', type=str, required=True, help='Output txt file (each line: gen_audio_path|text)')
parser.add_argument(
    '--vocos_checkpoint',
    type=str,
    default=str(REPO_ROOT / "vocos/generator.ckpt"),
    help='Vocos generator checkpoint path (.ckpt)',
)
parser.add_argument(
    '--vocos_root',
    type=str,
    default=str(REPO_ROOT),
    help='Path to repo root containing the vendored vocos package (default: this repo)',
)
parser.add_argument('--output_sample_rate', type=int, default=24000, help='Output wav sample rate')
parser.add_argument('--n_timesteps', type=int, default=4)
parser.add_argument('--length_scale', type=float, default=1.0)
parser.add_argument('--temperature', type=float, default=0.667)
parser.add_argument('--chunk_size', type=int, default=50, help='Streaming chunk size')
parser.add_argument('--mel_cache_len', type=int, default=8, help='Mel cache length for streaming')
parser.add_argument('--pre_lookahead_len', type=int, default=3, help='Pre-lookahead length for streaming')
parser.add_argument(
    '--num_decoding_left_chunks',
    type=int,
    default=-1,
    help='How many previous chunks each streaming step can attend to. '
         '-1 means all history, 0 means current chunk only, N means current + previous N chunks.',
)
parser.add_argument(
    '--add_blank',
    action='store_true',
    default=False,
    help='Whether to intersperse blank tokens (match training config add_blank).',
)
args = parser.parse_args()

MODEL_LANG = args.model_lang
LITS_CHECKPOINT = args.checkpoint
OUTPUT_FOLDER = args.output_dir
N_TIMESTEPS = args.n_timesteps
LENGTH_SCALE = args.length_scale
TEMPERATURE = args.temperature
OUTPUT_SAMPLE_RATE = args.output_sample_rate

MODEL2CLEANER = {
    "en-zh-dict": "en_zh_dict_mixed_cleaners",
    "en-zh": "pinyin_direct_mixed_cleaners",
    "ar-en": "ar_en_mixed_cleaners",
    "ar-en-dict": "ar_en_dict_mixed_cleaners",
    "bn-en": "bn_en_mixed_cleaners",
    "bn-en-dict": "bn_en_dict_mixed_cleaners",
    "en-ru": "en_ru_mixed_cleaners",
    "en-ru-dict": "en_ru_dict_mixed_cleaners",
}
CLEANER = MODEL2CLEANER[MODEL_LANG]


def load_model(checkpoint_path):
    model = LITS.load_from_checkpoint(checkpoint_path, map_location=DEVICE, weights_only=False)
    model.eval()
    return model


model = load_model(LITS_CHECKPOINT)
print(f"Model loaded successfully.")
print(f"Model stats: n_vocab={getattr(model, 'n_vocab', 'N/A')}, n_spks={getattr(model, 'n_spks', 'N/A')}")
if hasattr(model, "spk_emb"):
    print(f"Speaker embedding size: num_embeddings={model.spk_emb.num_embeddings}, dim={model.spk_emb.embedding_dim}")
if hasattr(model, "encoder") and hasattr(model.encoder, "emb"):
    print(f"Text embedding size: num_embeddings={model.encoder.emb.num_embeddings}, dim={model.encoder.emb.embedding_dim}")
if hasattr(model, "decoder") and hasattr(model.decoder, "num_decoding_left_chunks"):
    model.decoder.num_decoding_left_chunks = args.num_decoding_left_chunks
    if hasattr(model.decoder, "estimator"):
        model.decoder.estimator.num_decoding_left_chunks = args.num_decoding_left_chunks
    print(
        "Streaming decoder left chunk window: "
        f"{model.decoder.num_decoding_left_chunks} "
        "(-1 means all history)"
    )
elif args.num_decoding_left_chunks != -1:
    print(
        "[WARNING] --num_decoding_left_chunks was set, but model.decoder does not expose "
        "num_decoding_left_chunks. The limit may not take effect."
    )


def setup_vocoder(vocos_checkpoint, vocos_root):
    vocoder, vocoder_hparams = load_vocos_vocoder(vocos_checkpoint, DEVICE, vocos_root=vocos_root)
    vocoder_num_mels = int(vocoder_hparams.num_mels)
    vocoder_sample_rate = int(vocoder_hparams.sampling_rate)
    vocoder_output_hop = int(vocoder_hparams.hop_size)
    print(
        f"Vocoder loaded: Vocos ({vocos_checkpoint}, "
        f"n_mel={vocoder_num_mels}, hop={vocoder_output_hop}, sr={vocoder_sample_rate})"
    )
    return vocoder, vocoder_num_mels, vocoder_sample_rate, vocoder_output_hop


vocoder, vocoder_num_mels, vocoder_sample_rate, vocoder_output_hop = setup_vocoder(
    args.vocos_checkpoint,
    args.vocos_root,
)

if model.n_feats < vocoder_num_mels:
    raise ValueError(
        f"Mel channels mismatch: LITs outputs {model.n_feats} mel bins, "
        f"but vocoder expects {vocoder_num_mels}. "
        "Please use a vocoder checkpoint with matching mel bins."
    )
mel_trim_bins = vocoder_num_mels if model.n_feats > vocoder_num_mels else None
if mel_trim_bins is not None:
    print(
        f"[INFO] LITs outputs {model.n_feats} mel bands; "
        f"trimming to {mel_trim_bins} for vocoder."
    )
if OUTPUT_SAMPLE_RATE != vocoder_sample_rate:
    print(
        f"[WARNING] output_sample_rate={OUTPUT_SAMPLE_RATE} differs from vocoder config "
        f"sampling_rate={vocoder_sample_rate}. Consider setting --output_sample_rate {vocoder_sample_rate}."
    )


_CONTROL_CHARS_PATTERN = re.compile(
    r"[\x00-\x1f\x7f-\x9f"
    r"\u200b-\u200f"
    r"\u202a-\u202e"
    r"\u2066-\u2069"
    r"\ufeff\ufff9-\ufffb]"
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_HANZI_PATTERN = re.compile(r"[\u4e00-\u9fff]")

@torch.inference_mode()
def process_text(text: str):
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_CHARS_PATTERN.sub("", text)
    text = _WHITESPACE_PATTERN.sub(" ", text).strip()
    if MODEL_LANG == "en-zh" and _HANZI_PATTERN.search(text):
        raise ValueError(
            "Raw Hanzi input requires --model_lang en-zh-dict. "
            "--model_lang en-zh expects pre-tokenized numbered pinyin/ARPAbet input; "
            "using it with Chinese characters maps most Hanzi to unknown tokens and loses semantics."
        )

    token_ids, cleaned_text = text_to_sequence(text, [CLEANER])
    if args.add_blank:
        token_ids = intersperse(token_ids, 0)

    x = torch.tensor(token_ids, dtype=torch.long, device=DEVICE)[None]
    x_lengths = torch.tensor([x.shape[-1]], dtype=torch.long, device=DEVICE)
    return {
        'x_orig': text,
        'x_text': cleaned_text,
        'x': x,
        'x_lengths': x_lengths,
    }


@torch.inference_mode()
def synthesise(text=None, spks=None, text_processed=None):
    if text_processed is None:
        if text is None:
            raise ValueError("Either `text` or `text_processed` must be provided.")
        text_processed = process_text(text)
    start_t = dt.datetime.now()
    output = model.get_hidden_mel(
        text_processed['x'],
        text_processed['x_lengths'],
        spks=spks,
        length_scale=LENGTH_SCALE,
    )
    output.update({'start_t': start_t, **text_processed})
    return output


_PINYIN_PATTERN = re.compile(r"^[a-z]+[0-5]$")
_NON_ENGLISH_SPK_PATTERN = re.compile(
    r"[\u4e00-\u9fff\u0600-\u06ff\u0980-\u09ff\u0400-\u04ff\u0300-\u0301]"
)


def _infer_spk_id_from_text(text: str):
    """Infer speaker from text content.

    en-zh mode: any Hanzi or pinyin token -> Chinese (spk=1), else English (spk=0).
    Other modes (ar-en, bn-en, en-ru): non-English script detected -> spk=1, else spk=0.
    en-ru: Cyrillic -> Russian (spk=1), ARPAbet/ASCII -> English (spk=0).
    """
    if MODEL_LANG in ("en-zh", "en-zh-dict"):
        if _NON_ENGLISH_SPK_PATTERN.search(text):
            return 1
        tokens = text.strip().split()
        for t in tokens:
            if t in ("_", "/", "|"):
                continue
            if _PINYIN_PATTERN.match(t):
                return 1
        return 0
    return 1 if _NON_ENGLISH_SPK_PATTERN.search(text) else 0


def parse_input_line(line: str):
    """Support formats: wav_path|text (2-field) or wav_path|spk_id|text (3-field)."""
    parts = line.strip().split("|")
    if len(parts) == 3:
        wav_path, spk_id_str, text = parts
        return wav_path, int(spk_id_str), text
    elif len(parts) == 2:
        wav_path, text = parts
        spk_id = _infer_spk_id_from_text(text)
        return wav_path, spk_id, text
    else:
        raise ValueError("Invalid input format, expected 'wav_path|text' or 'wav_path|spk_id|text'")


def _validate_token_range(x: torch.Tensor):
    if x.numel() == 0:
        raise ValueError("Empty token sequence after tokenization.")
    model_n_vocab = int(getattr(model, "n_vocab", 0))
    token_min = int(x.min().item())
    token_max = int(x.max().item())
    if token_min < 0 or token_max >= model_n_vocab:
        raise ValueError(
            f"Token id out of range: min={token_min}, max={token_max}, "
            f"but model.n_vocab={model_n_vocab}. "
            "Checkpoint and frontend tokenizer are likely mismatched."
        )


def fade_in_out(fade_in_mel, fade_out_mel, window):
    device = fade_in_mel.device
    fade_in_mel, fade_out_mel = fade_in_mel.cpu(), fade_out_mel.cpu()
    mel_overlap_len = int(window.shape[0] / 2)
    if fade_in_mel.device == torch.device('cpu'):
        fade_in_mel = fade_in_mel.clone()
    fade_in_mel[..., :mel_overlap_len] = fade_in_mel[..., :mel_overlap_len] * window[:mel_overlap_len] + \
        fade_out_mel[..., -mel_overlap_len:] * window[mel_overlap_len:]
    return fade_in_mel.to(device)


@torch.inference_mode()
def to_waveform(mel, vocoder):
    if mel_trim_bins is not None:
        mel = mel[:, :mel_trim_bins, :]
    audio = vocoder(mel).clamp(-1, 1)
    target_len = int(mel.shape[-1] * vocoder_output_hop)
    audio = audio[..., :target_len]
    audio = audio.squeeze(0)
    return audio.cpu().squeeze()


def save_to_folder(filename: str, waveform: torch.Tensor, folder: str):
    folder = Path(folder)
    folder.mkdir(exist_ok=True, parents=True)
    sf.write(folder / f'{filename}.wav', waveform.cpu().numpy(), OUTPUT_SAMPLE_RATE, 'PCM_24')


def streaming_synthesise(text, chunk_size, mel_cache_len, pre_lookahead_len, speech_window, spks=None):
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    start_time = time.perf_counter()
    text_processed = process_text(text)
    _validate_token_range(text_processed["x"])
    output = synthesise(spks=spks, text_processed=text_processed)

    first_latency = None
    vocoder_cache = {}

    pad = output['y_max_length'] % chunk_size
    slice_id = range(0, output['y_max_length']-pad, chunk_size) if output['y_max_length']-pad > 0 else [0]
    all_waveforms = []

    # Pre-generate global noise so every chunk reuses the same z at the same
    # position, eliminating phase inconsistency at chunk boundaries.
    global_z = torch.randn(
        1, model.n_feats, output['y_max_length'],
        device=DEVICE,
    ) * TEMPERATURE

    if hasattr(model.decoder, "reset_encoder_cache"):
        model.decoder.reset_encoder_cache()

    for j, start_idx in enumerate(slice_id):
        finalize = False

        if start_idx != slice_id[-1]:
            end_idx = start_idx + chunk_size + pre_lookahead_len
        else:
            end_idx = output['y_max_length']
            finalize = True

        if finalize:
            encoder_outputs = output['mu_y'][:, :, :end_idx]
            y_mask = output['y_mask'][:, :, :end_idx]
        else:
            encoder_outputs = output['mu_y'][:, :, :end_idx]
            y_mask = output['y_mask'][:, :, :end_idx-pre_lookahead_len]

        spks = output['spks'] if 'spks' in output else None

        mel = model.get_mel(
            mu_y=encoder_outputs,
            y_mask=y_mask,
            spks=spks,
            n_timesteps=N_TIMESTEPS,
            finalize=finalize,
            temperature=TEMPERATURE,
            streaming=True,
            z=global_z[:, :, :end_idx],
            chunk_start=start_idx,
        )[0, :, start_idx:].unsqueeze(0)

        if first_latency is None:
            if torch.cuda.is_available():
                torch.cuda.synchronize()
            first_latency = (time.perf_counter() - start_time) * 1000

        if vocoder_cache != {}:
            mel = torch.concat([vocoder_cache['mel'], mel], dim=2)

        if start_idx != slice_id[-1]:
            waveform = to_waveform(mel, vocoder).unsqueeze(0)

            if 'waveform' in vocoder_cache:
                waveform = fade_in_out(waveform, vocoder_cache['waveform'], speech_window)

            mel = mel[:, :, -mel_cache_len:]
            vocoder_cache['mel'] = mel
            source_cache_len = int(mel_cache_len * vocoder_output_hop)
            vocoder_cache['waveform'] = waveform[:, -source_cache_len:]
            waveform = waveform[:, :-source_cache_len][0]

        else:
            waveform = to_waveform(mel, vocoder).unsqueeze(0)
            if 'waveform' in vocoder_cache:
                waveform = fade_in_out(waveform, vocoder_cache['waveform'], speech_window)[0]
            else:
                waveform = waveform[0]

        all_waveforms.append(waveform.squeeze())

    final_waveform = torch.cat(all_waveforms, dim=0)

    if torch.cuda.is_available():
        torch.cuda.synchronize()
    end_time = time.perf_counter()
    total_time = end_time - start_time
    rtf = total_time * OUTPUT_SAMPLE_RATE / final_waveform.shape[-1]

    return {
        'waveform': final_waveform,
        'rtf': rtf,
        'first_latency': first_latency,
        'start_t': output['start_t'],
        'mel_frames': int(output['y_max_length']),
        'wav_samples': int(final_waveform.shape[-1]),
    }


def batch_inference(input_txt_path, output_dir, output_txt_path=None):
    chunk_size = args.chunk_size
    mel_cache_len = args.mel_cache_len
    source_cache_len = int(mel_cache_len * vocoder_output_hop)
    speech_window = np.hanning(2 * source_cache_len)
    pre_lookahead_len = args.pre_lookahead_len

    rtfs = []
    rtfs_w = []
    first_latency_list = []
    failures = 0
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_txt_lines = []

    with open(input_txt_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    spk_upper_bound = None
    if getattr(model, "n_spks", 1) > 1:
        if hasattr(model, "spk_emb"):
            spk_upper_bound = int(model.spk_emb.num_embeddings) - 1
        else:
            spk_upper_bound = int(model.n_spks) - 1

    for i, line in enumerate(tqdm(lines)):
        try:
            wav_path, spk_id, text = parse_input_line(line)
            base_name = Path(wav_path).stem

            spks = None
            if model.n_spks > 1:
                if spk_upper_bound is None:
                    raise ValueError("Model indicates multi-speaker but speaker embedding is missing.")
                if not (0 <= spk_id <= spk_upper_bound):
                    raise ValueError(
                        f"spk_id out of range: {spk_id}, expected [0, {spk_upper_bound}] "
                        f"(model.n_spks={model.n_spks})"
                    )
                spks = torch.tensor([spk_id], device=DEVICE, dtype=torch.long)

            result = streaming_synthesise(text, chunk_size, mel_cache_len, pre_lookahead_len, speech_window, spks=spks)

            t = (dt.datetime.now() - result['start_t']).total_seconds()
            rtf_w = t * OUTPUT_SAMPLE_RATE / result['waveform'].shape[-1]

            rtfs.append(result['rtf'])
            rtfs_w.append(rtf_w)
            first_latency_list.append(result['first_latency'])

            save_to_folder(base_name, result['waveform'], output_dir)
            out_wav_path = str(output_dir / f"{base_name}.wav")
            output_txt_lines.append(f"{out_wav_path}|{text}")
            print(
                f"[DEBUG_LENGTH] {base_name}: mel_frames={result['mel_frames']}, "
                f"wav_samples={result['wav_samples']}, "
                f"wav_sec={result['wav_samples'] / OUTPUT_SAMPLE_RATE:.3f}"
            )
            print(f"[{i+1}/{len(lines)}] Synthesized and saved: {base_name}.wav")

        except Exception as e:
            failures += 1
            print(f"[{i+1}/{len(lines)}] Error processing line: {line.strip()}")
            print(e)
            traceback.print_exc()
            if torch.cuda.is_available() and "device-side assert triggered" in str(e):
                print("CUDA context is now invalid after device-side assert. Stop early and fix the first failing sample.")
                break

    if output_txt_path:
        with open(output_txt_path, "w", encoding="utf-8") as f:
            for l in output_txt_lines:
                f.write(l + "\n")
        print(f"Output list saved to: {output_txt_path}")

    print(f"Number of ODE steps: {N_TIMESTEPS}")
    print(f"Chunk size: {chunk_size}")
    print(f"Num decoding left chunks: {args.num_decoding_left_chunks}")
    print(f"Successful items: {len(rtfs)}/{len(lines)}")
    if failures:
        print(f"Failed items: {failures}/{len(lines)}")
    if rtfs:
        print(f"Mean RTF:\t\t\t\t{np.mean(rtfs):.6f} ± {np.std(rtfs):.6f}")
        print(f"Mean RTF Waveform (incl. vocoder):\t{np.mean(rtfs_w):.6f} ± {np.std(rtfs_w):.6f}")
    if first_latency_list:
        print(f"First Latency: {sum(first_latency_list)/len(first_latency_list):.2f} ms")
    if not rtfs:
        raise SystemExit("No audio was generated successfully.")


if __name__ == "__main__":
    batch_inference(args.input_txt, args.output_dir, args.output_txt)
