#!/usr/bin/env python3
"""Build the SDK's WeTextProcessing 1.0.4.1 graphs without deleting speech.

Keep the shipped tagger byte-for-byte. The verbalizer construction below follows
WeTextProcessing 1.0.4.1's build_verbalizer (Apache-2.0, Xingchen Song), with only
PostProcessor.remove_interjections disabled. That release hardcodes it to True
and ships cached FSTs, so constructing InverseNormalizer alone cannot fix them.
"""

import argparse
from importlib.resources import files
from pathlib import Path
import shutil


def build(cache_dir: Path) -> None:
    from itn.chinese import inverse_normalizer as rules

    normalizer = rules.InverseNormalizer()
    verbalizer = (
        rules.Cardinal(normalizer.convert_number, normalizer.enable_0_to_9,
                       normalizer.enable_million).verbalizer
        | rules.Char().verbalizer
        | rules.Date().verbalizer
        | rules.Fraction().verbalizer
        | rules.Math().verbalizer
        | rules.Measure(enable_0_to_9=normalizer.enable_0_to_9).verbalizer
        | rules.Money(enable_0_to_9=normalizer.enable_0_to_9).verbalizer
        | rules.Time().verbalizer
        | rules.LicensePlate().verbalizer
        | rules.Whitelist().verbalizer
    ).optimize()
    postprocessor = rules.PostProcessor(remove_interjections=False).processor
    normalizer.verbalizer = (verbalizer @ postprocessor).star
    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(files("itn") / "zh_itn_tagger.fst", cache_dir / "zh_itn_tagger.fst")
    normalizer.verbalizer.optimize().write(str(cache_dir / "zh_itn_verbalizer.fst"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cache_dir", type=Path)
    build(parser.parse_args().cache_dir)
