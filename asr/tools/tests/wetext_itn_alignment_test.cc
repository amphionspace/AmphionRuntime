// Run against the pinned WeText processor and packaged ZH ITN FSTs.
#include <cassert>
#include <filesystem>
#include <string>
#include <vector>

#include "processor/wetext_processor.h"

static void Check(wetext::Processor& processor, const std::string& source,
                  const std::string& replaced = "",
                  const std::string& replacement = "") {
  const auto result = processor.NormalizeWithAlignment(source);
  assert(result.text == processor.Normalize(source));
  size_t source_end = 0, text_end = 0;
  bool found = replaced.empty();
  for (const auto& span : result.spans) {
    assert(span.source_begin == source_end && span.text_begin == text_end);
    assert(span.source_end > source_end && span.text_end >= text_end);
    const auto raw = source.substr(span.source_begin, span.source_end - span.source_begin);
    const auto text = result.text.substr(span.text_begin, span.text_end - span.text_begin);
    if (raw == replaced && text == replacement) found = true;
    source_end = span.source_end;
    text_end = span.text_end;
  }
  assert(source_end == source.size() && text_end == result.text.size());
  assert(found);
}

// Deliberately delay all output until the entire input has been consumed.
// The string is valid, but record-level input ownership cannot be recovered.
static void Delayed(const std::string& input, const std::string& output,
                    const std::filesystem::path& path) {
  fst::StdVectorFst graph;
  graph.AddState(); graph.SetStart(0);
  int state = 0;
  for (unsigned char byte : input) {
    graph.AddState(); graph.AddArc(state, fst::StdArc(byte, 0, 0, state + 1)); ++state;
  }
  for (unsigned char byte : output) {
    graph.AddState(); graph.AddArc(state, fst::StdArc(0, byte, 0, state + 1)); ++state;
  }
  graph.SetFinal(state, 0);
  assert(graph.Write(path.string()));
}

int main(int argc, char** argv) {
  assert(argc == 4);
  wetext::Processor processor(argv[1], argv[2]);
  Check(processor, "");
  Check(processor, "到了一百二十秒再说你好", "一百二十秒", "120s");
  Check(processor, "九十中间结果", "九十", "90");
  Check(processor, "百分之三", "百分之三", "3%");
  Check(processor, "二零二六年五月十五日", "二零二六年五月十五日", "2026/05/15");
  Check(processor, "两点五八万", "两点五八万", "2.58万");
  Check(processor, "𠮷野一百元", "一百元", "¥100");
  Check(processor, "甲乙甲乙");
  Check(processor, " hello world ");
  Check(processor, "编号一二三四么六七八九零么");
  Check(processor, "“你好”");
  const auto tagger = std::filesystem::path(argv[3]) / "zh_itn_tagger.fst";
  const auto verbalizer = std::filesystem::path(argv[3]) / "zh_itn_verbalizer.fst";
  const std::string records = "char { value: \"A\" } char { value: \"B\" }";
  Delayed("AB", records, tagger);
  Delayed(records, "AB", verbalizer);
  wetext::Processor delayed(tagger.string(), verbalizer.string());
  const auto uncertain = delayed.NormalizeWithAlignment("AB");
  assert(uncertain.text == "AB");
  assert(uncertain.spans.empty());
}
