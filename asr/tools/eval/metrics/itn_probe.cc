#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
#include <utility>
#include <iostream>

namespace {

// "么" is a common ASR spelling for spoken digit one (yao), but it is also a
// normal Chinese suffix. Length alone is insufficient: "这么1234" is a
// five-token digit-like run but is still grammatical text. Require either a
// numeric-field context separated only by punctuation/whitespace, a standard
// identifier length, or an ambiguous token inside an already numeric run.
constexpr int32_t kMinAmbiguousDigitRunLength = 5;
constexpr int32_t kMinEmbeddedAmbiguousDigitRunLength = 7;
constexpr size_t kMaxNumericContextGapBytes = 9;

bool HasOnlyNumericFieldSeparators(const std::string &input, size_t begin,
                                   size_t end) {
  static const char *kSeparators[] = {
      " ", "\t", "\r", "\n", ":", "：", ",", "，", "、",
      "-", "－", ".", "。"};
  size_t offset = begin;
  while (offset < end) {
    bool matched = false;
    for (const char *separator : kSeparators) {
      const std::string value(separator);
      if (input.compare(offset, value.size(), value) == 0) {
        offset += value.size();
        matched = true;
        break;
      }
    }
    if (!matched) return false;
  }
  return true;
}

bool HasRecentNumericField(const std::string &input, size_t run_start) {
  static const char *kNumericFields[] = {
      "身份证号码", "身份证号", "身份证", "手机号码", "手机号",
      "电话号码", "电话", "验证码", "证件号", "卡号", "账号",
      "编号", "工号", "序号", "邮编", "号码"};
  for (const char *field : kNumericFields) {
    const std::string value(field);
    const size_t pos = input.rfind(value, run_start);
    const size_t field_end = pos == std::string::npos ? 0 : pos + value.size();
    if (pos != std::string::npos && field_end <= run_start &&
        run_start - field_end <= kMaxNumericContextGapBytes &&
        HasOnlyNumericFieldSeparators(input, field_end, run_start)) {
      return true;
    }
  }
  return false;
}

bool HasGrammaticalPrefix(const std::string &input, size_t run_start) {
  static const char *kPrefixes[] = {"这", "什", "怎", "那", "多"};
  for (const char *prefix : kPrefixes) {
    const std::string value(prefix);
    if (run_start >= value.size() &&
        input.compare(run_start - value.size(), value.size(), value) == 0) {
      return true;
    }
  }
  return false;
}

bool IsStandardIdentifierLength(int32_t run_length) {
  return run_length == 11 || run_length == 15 || run_length == 18;
}

bool MatchDigitToken(const std::string &input, size_t offset,
                     std::string *token, bool *is_ambiguous_one) {
  static const char *kDigitTokens[] = {
      "零", "〇", "一", "二", "三", "四", "五", "六", "七",
      "八", "九", "幺", "么", "两"};
  if (offset < input.size() && input[offset] >= '0' && input[offset] <= '9') {
    *token = input.substr(offset, 1);
    *is_ambiguous_one = false;
    return true;
  }
  for (const char *candidate : kDigitTokens) {
    const std::string value(candidate);
    if (input.compare(offset, value.size(), value) == 0) {
      *token = value;
      *is_ambiguous_one = value == "么";
      return true;
    }
  }
  return false;
}

// Spoken digit runs (念「一二三四五六七八九十」) are read out one digit at a time,
// but the upstream tagger groups them into `123 4567 80~90`: it splits the run and
// renders a trailing 十 as an approximate range. Rewrite such a run to its digits
// before tagging so the reading survives. Compound cardinals, dates and measures
// keep their grammars: the run needs at least three items, a trailing 十 is only
// absorbed when at least two digits precede it and nothing numeric follows, and a
// unit directly after the run hands the whole thing back to the tagger.
// `source_map` keeps, for every byte of the rewritten text, the byte offset it came
// from in `input`, so alignment spans can be reported in the caller's coordinates.
std::string CollapseSpokenDigitRuns(const std::string &input,
                                    std::vector<size_t> *source_map) {
  static const std::pair<const char *, const char *> kDigits[] = {
      {"零", "0"}, {"〇", "0"}, {"一", "1"}, {"二", "2"}, {"三", "3"},
      {"四", "4"}, {"五", "5"}, {"六", "6"}, {"七", "7"}, {"八", "8"},
      {"九", "9"}, {"幺", "1"}, {"么", "1"}, {"两", "2"}};
  // A unit right after the run means a date, a measure or a money amount; those
  // grammars read the spoken form and must keep it.
  static const char *kUnits[] = {
      "年", "月", "日", "时", "分", "秒", "点", "元", "块", "角", "毛",
      "度", "岁", "号", "个", "百", "千", "万", "亿", "兆", "％", ".", "%"};
  static const char *kShi = "十";

  auto digit_at = [&](size_t offset, std::string *digit) -> size_t {
    if (offset < input.size() && input[offset] >= '0' && input[offset] <= '9') {
      *digit = input.substr(offset, 1);
      return 1;
    }
    for (const auto &entry : kDigits) {
      const std::string token(entry.first);
      if (input.compare(offset, token.size(), token) == 0) {
        *digit = entry.second;
        return token.size();
      }
    }
    return 0;
  };
  auto unit_at = [&](size_t offset) -> bool {
    for (const char *unit : kUnits) {
      const std::string token(unit);
      if (input.compare(offset, token.size(), token) == 0) return true;
    }
    return false;
  };

  // `map[k]` is the offset in `input` reached after consuming `k` bytes of the
  // rewritten text, so the last byte of a rewritten item carries the end of the
  // source it replaced. Callers read end offsets, which is what spans need.
  std::string output;
  std::vector<size_t> map;
  output.reserve(input.size());
  map.reserve(input.size() + 1);
  map.push_back(0);
  auto emit = [&](const std::string &text, size_t begin, size_t end) {
    for (size_t k = 0; k < text.size(); ++k) {
      output.push_back(text[k]);
      map.push_back(k + 1 == text.size() ? end : begin);
    }
  };

  size_t offset = 0;
  while (offset < input.size()) {
    std::string digit;
    size_t width = digit_at(offset, &digit);
    if (width == 0) {
      emit(input.substr(offset, 1), offset, offset + 1);
      offset += 1;
      continue;
    }
    const size_t run_start = offset;
    std::vector<std::tuple<std::string, size_t, size_t>> items;
    while ((width = digit_at(offset, &digit)) != 0) {
      items.emplace_back(digit, offset, offset + width);
      offset += width;
    }
    const std::string shi(kShi);
    bool absorbed_shi = false;
    if (items.size() >= 2 && input.compare(offset, shi.size(), shi) == 0) {
      const size_t after = offset + shi.size();
      std::string ignored;
      if (digit_at(after, &ignored) == 0 && !unit_at(after)) {
        items.emplace_back("10", offset, after);
        offset = after;
        absorbed_shi = true;
      }
    }
    if (items.size() >= 3 && !unit_at(offset)) {
      for (const auto &item : items) {
        emit(std::get<0>(item), std::get<1>(item), std::get<2>(item));
      }
      continue;
    }
    // Not a spoken run: hand the original bytes back, byte for byte.
    (void)absorbed_shi;
    for (size_t q = run_start; q < offset; ++q) {
      emit(input.substr(q, 1), q, q + 1);
    }
  }
  if (source_map != nullptr) *source_map = map;
  return output;
}

std::string CanonicalizeAmbiguousDigitOne(const std::string &input) {
  std::string output;
  output.reserve(input.size());
  size_t offset = 0;
  while (offset < input.size()) {
    std::string token;
    bool is_ambiguous_one = false;
    if (!MatchDigitToken(input, offset, &token, &is_ambiguous_one)) {
      output.push_back(input[offset++]);
      continue;
    }

    const size_t run_start = offset;
    int32_t run_length = 0;
    bool has_ambiguous_one = false;
    bool ambiguous_at_run_start = false;
    bool has_unambiguous_digit = false;
    std::string canonical_run;
    while (MatchDigitToken(input, offset, &token, &is_ambiguous_one)) {
      if (run_length == 0) ambiguous_at_run_start = is_ambiguous_one;
      ++run_length;
      has_ambiguous_one = has_ambiguous_one || is_ambiguous_one;
      has_unambiguous_digit = has_unambiguous_digit || !is_ambiguous_one;
      canonical_run.append(is_ambiguous_one ? "幺" : token);
      offset += token.size();
    }
    const bool grammatical_ambiguous_start =
        ambiguous_at_run_start && HasGrammaticalPrefix(input, run_start);
    const bool trusted_numeric_shape = !grammatical_ambiguous_start &&
        (HasRecentNumericField(input, run_start) ||
         IsStandardIdentifierLength(run_length) ||
         (!ambiguous_at_run_start &&
          run_length >= kMinEmbeddedAmbiguousDigitRunLength));
    if (run_length >= kMinAmbiguousDigitRunLength && has_ambiguous_one &&
        has_unambiguous_digit && trusted_numeric_shape) {
      output.append(canonical_run);
    } else {
      output.append(input, run_start, offset - run_start);
    }
  }
  return output;
}

}  // namespace

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.empty()) continue;
    std::vector<size_t> smap;
    std::string canon = CanonicalizeAmbiguousDigitOne(line);
    std::string collapsed = CollapseSpokenDigitRuns(canon, &smap);
    printf("IN       : %s\nCANON    : %s\nCOLLAPSED: %s\n\n",
           line.c_str(), canon.c_str(), collapsed.c_str());
  }
  return 0;
}
