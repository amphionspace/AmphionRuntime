"""Accepted training reuse: real fit boundaries and two independent Cluster oracles.

Synthetic vectors only. The portable 1c fixture freezes the complete pre-change
Cluster; it shares unchanged helpers/Ahc, never a rewritten production Cluster.
The older parity reference additionally supplies independent Ahc and Reconstruct.
Instrumentation in a temporary header only observes real entry/return boundaries,
requests cancellation, or injects std::bad_alloc at real Ahc entry to check
propagation. It does not replace an algorithm or allocator, or simulate allocator
failure. No test needs Git or .cache artifacts.
"""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from asr.tools.tests import test_harmony_community_cluster_parity as parity

CPP = parity.CPP
FIXTURE = Path(__file__).with_name('community_cluster_accepted_training_reference.h')
FIXTURE_SHA256 = 'c4707ac2b7a588a9167c914b12b9105baa7c1e2280f6c64a140cab2722ba670e'
CLUSTER_SHA256 = '6cbdfb4caab3aea86aa657396920aae600e2d12b37c42dcc55221fb63314a46d'

OBSERVER = r'''
#pragma once
#include "community_cancel.h"
#include <new>
#include <vector>
namespace reuse_probe {
struct Observation {
  std::vector<size_t> rows;
  std::vector<std::vector<int>> labels;
  int finalEntries=0,pldaEntries=0,vbxEntries=0;
};
inline Observation seen;
inline size_t failFit=0;
inline community::CancellationToken* cancelBeforeReuse=nullptr;
inline void Reset() { seen={};failFit=0;cancelBeforeReuse=nullptr; }
inline void FitEntered(size_t rows) {
  seen.rows.push_back(rows);
  // Synthetic entry fault for propagation, not a real allocator failure.
  // The original code next initializes n and allocates centers.
  if(failFit&&seen.rows.size()==failFit)throw std::bad_alloc();
}
inline void FitReturned(const std::vector<int>& labels) { seen.labels.push_back(labels); }
inline void BeforeFinal() {
  ++seen.finalEntries;
  if(cancelBeforeReuse)cancelBeforeReuse->Cancel();
}
inline void PldaEntered() { ++seen.pldaEntries; }
inline void VbxEntered() { ++seen.vbxEntries; }
}
'''


def instrument(header):
    """Insert observers at real boundaries; leave all algorithm statements intact."""
    def insert(anchor, replacement):
        nonlocal header
        if header.count(anchor) != 1:
            raise AssertionError(f'observation boundary must be unique: {anchor}')
        header = header.replace(anchor, replacement)

    header = '#include "reuse_observer.h"\n' + header
    entry = 'inline std::vector<int> Ahc(const Matrix& x, const CancellationToken* cancellation) {'
    insert(entry, entry + '\n  reuse_probe::FitEntered(x.size());')
    insert('cut(2*n-2);return labels;',
           'cut(2*n-2);reuse_probe::FitReturned(labels);return labels;')
    entry = 'Matrix Apply(const Matrix& input, const CancellationToken* cancellation = nullptr) const {'
    insert(entry, entry + '\n    reuse_probe::PldaEntered();')
    entry = ('inline VbxResult Vbx(const Matrix& x,const Vec& phi,const std::vector<int>& initial,\n'
             '                      const CancellationToken* cancellation = nullptr) {')
    insert(entry, entry + '\n  reuse_probe::VbxEntered();')
    entry = 'if(train.size()==1)result.centroids=Matrix(1,train[0]);\n  else {'
    insert(entry, entry + '\n    reuse_probe::BeforeFinal();')
    return header


HARNESS = r'''
community::ClusterResult Run(const Input& x,bool frozen=false,
                             const community::CancellationToken* token=nullptr) {
  auto p=MakePlda<community::Plda>(x.phi);
  if(frozen)return accepted_training_reference::Cluster(x.segments,x.embeddings,x.windows,p,
                                                        x.cap,x.runs,x.ranges,x.rms,token);
  return community::Cluster(x.segments,x.embeddings,x.windows,p,x.cap,x.runs,x.ranges,x.rms,token);
}
void CheckTurns(const Input& x,const community::ClusterResult& a,const community::ClusterResult& b) {
  if(x.windows>0)for(bool frame:{false,true}) {
    auto oldTurns=reference::Reconstruct(x.segments,b.hard,x.starts,x.begin,x.cap,
                                         frame?b.frame_hard:std::vector<int>{});
    auto newTurns=community::Reconstruct(x.segments,a.hard,x.starts,x.begin,x.cap,
                                         frame?a.frame_hard:std::vector<int>{});
    EqualTurns(newTurns,oldTurns,frame?"frameTurns":"windowTurns");
  }
}
struct Checked {
  community::ClusterResult result;
  reuse_probe::Observation before,after;
};
void PrintRows(const std::vector<size_t>& rows) {
  std::cout<<'[';
  for(size_t i=0;i<rows.size();++i)std::cout<<(i?",":"")<<rows[i];
  std::cout<<']';
}
Checked Check(const Input& x,const std::string& name,
              const std::vector<size_t>& beforeRows,const std::vector<size_t>& afterRows) {
  context=name;
  auto independent=reference::Cluster(x.segments,x.embeddings,x.windows,
      MakePlda<community::Plda>(x.phi),x.cap,x.runs,x.ranges,x.rms);
  reuse_probe::Reset();
  auto frozen=Run(x,true);auto before=reuse_probe::seen;
  reuse_probe::Reset();
  auto actual=Run(x);auto after=reuse_probe::seen;
  // Compare outputs before work assertions, so red proves redundant work with
  // otherwise identical results, not a changed fixture or oracle.
  EqualResult(frozen,independent);EqualResult(actual,independent);EqualResult(actual,frozen);
  CheckTurns(x,frozen,independent);CheckTurns(x,actual,independent);
  std::cout<<name<<" outputs=bitwise-equal baseline=";PrintRows(before.rows);
  std::cout<<" current=";PrintRows(after.rows);std::cout<<'\n';
  Equal(before.rows,beforeRows,"baseline actual Ahc rows");
  Equal(after.rows,afterRows,"current actual Ahc rows");
  ++comparisons;
  return {std::move(actual),std::move(before),std::move(after)};
}
Input TwoLong(int n=2) {
  Input x(n);x.Voice(0,0,0,150,0);x.Voice(1,0,0,150,1);return x;
}
Input Mixed() {
  Input x=TwoLong(6);
  // e2 is accepted, e0 is rejected, e3 is accepted. The final e4 tail is
  // skipped after saturation. A later case ends with a rejected proposal.
  x.Voice(2,0,0,68,2);x.Voice(3,0,0,68,0);
  x.Voice(4,0,0,68,3);x.Voice(5,0,0,68,4);return x;
}
void NoShortAndCap() {
  Check(TwoLong(),"no-short",{2,2},{2});
  auto x=TwoLong(6);x.cap=2;
  for(int w=2;w<x.windows;++w)x.Voice(w,0,0,68,w);
  auto r=Check(x,"already-saturated-short-tail",{2,2},{2});
  Equal(r.result.trainingRunIndices,std::vector<int>{0,1},"saturated training");
  Require(r.result.shortRunTrainingCount==0,"saturated proposals must stay unadmitted");
}
void AcceptedRejected() {
  auto x=Mixed();
  auto r=Check(x,"accepted-rejected-accepted-cap",{2,3,4,4,4},{2,3,4,4});
  Equal(r.result.trainingRunIndices,std::vector<int>{0,1,2,4},"admission order");
  Require(r.result.shortRunTrainingCount==2,"exactly two admissions");
  Equal(r.result.ahc,r.after.labels[3],"complete last accepted labels");
  auto trailing=TwoLong(4);
  trailing.Voice(2,0,0,68,2);trailing.Voice(3,0,0,68,0);
  auto rejected=Check(trailing,"accepted-then-final-rejected",{2,3,4,3},{2,3,4});
  Equal(rejected.result.trainingRunIndices,std::vector<int>{0,1,2},"rejected stays out of train");
  Equal(rejected.result.ahc,rejected.after.labels[1],"rejected labels must not replace accepted labels");
  Require(rejected.after.labels[2].size()!=rejected.result.ahc.size(),"rejection is observable");
}
void Renumbering() {
  auto x=TwoLong(3);
  auto candidate=Axis(2);candidate[0]=.6f;candidate[2]=.8f;
  x.Speech(2,0,0,68);x.Full(2,0,candidate);x.Run(2,0,0,68,candidate);
  auto r=Check(x,"accepted-renumbers-old-rows",{2,3,3},{2,3});
  Require(r.after.labels.size()==2,"initial and proposal labels observed");
  const auto& initial=r.after.labels[0];const auto& proposal=r.after.labels[1];
  Require(initial.size()==2&&proposal.size()==3,"complete proposal fit");
  Require(!std::equal(initial.begin(),initial.end(),proposal.begin()),"fixture must change old row IDs");
  auto appendOnly=initial;appendOnly.push_back(proposal.back());
  Require(appendOnly!=proposal,"appending only a final label would fail");
  Equal(r.result.ahc,proposal,"all accepted labels replaced");
  std::cout<<"observed initial labels ";PrintRows(std::vector<size_t>(initial.begin(),initial.end()));
  std::cout<<" accepted labels ";PrintRows(std::vector<size_t>(proposal.begin(),proposal.end()));std::cout<<'\n';
}
void EmptySingleLegacy() {
  Input none(1);none.Voice(0,0,0,68,0);
  auto empty=Check(none,"empty-training-run-mode",{},{}).result;
  Equal(empty.hard,std::vector<int>(local,-2),"empty hard");
  EqualResult(empty,[] {community::ClusterResult r;r.hard.assign(local,-2);return r;}());
  Input one(2);one.Voice(0,0,0,150,0);one.Voice(1,0,0,68,0);
  auto single=Check(one,"single-training-rejected-proposal",{1,2},{1,2}).result;
  Require(single.centroids.size()==1&&single.shortRunTrainingCount==0,"single centroid");
  Require(single.ahc.empty()&&single.features.empty()&&single.vbx.q.empty()&&
          single.vbx.priors.empty()&&single.vbx.objectives.empty(),"single public fields remain empty");
  Input legacy(2);
  for(int w=0;w<2;++w){legacy.Speech(w,0,0,150);legacy.Full(w,0,Axis(w));}
  auto old=Check(legacy,"legacy-final-fit-kept",{2},{2}).result;
  Require(old.trainingIndices==std::vector<int>({0,3})&&!old.ahc.empty(),"legacy final fit");
}
void Recovery() {
  for(bool sameLong:{false,true}) {
    Input x(6);x.phi=10.;
    for(int w=0;w<6;++w)x.Voice(w,0,0,w==5?68:200,sameLong?(w==5?1:0):(w<4?0:w-3));
    auto r=Check(x,sameLong?"short-recovery":"long-vbx-merge-protected",{5,6,6},{5,6}).result;
    Require(r.shortRunTrainingCount==1,"short still admitted");
    Require(r.usedAhcFallback==sameLong,"short recovery decision");
    Require(r.centroids.size()==(sameLong?2u:1u),"long partition must stay merged");
  }
}
void CancelSeam() {
  for(bool finalRejected:{false,true}) {
    Input x=finalRejected?TwoLong(4):Mixed();
    if(finalRejected){x.Voice(2,0,0,68,2);x.Voice(3,0,0,68,0);}
    context=finalRejected?"cancel-after-rejected-proposal":"cancel-after-accepted-proposal";
    community::CancellationToken token;
    reuse_probe::Reset();reuse_probe::cancelBeforeReuse=&token;
    community::ClusterResult published;published.hard={97531};
    const auto sentinel=published;bool cancelled=false;
    try { published=Run(x,false,&token); }
    catch(const std::runtime_error& error) {cancelled=std::string(error.what())=="Community operation cancelled";}
    const auto observed=reuse_probe::seen;
    Require(token.IsCancelled()&&cancelled,"reuse entry must throw cancellation");
    Require(observed.finalEntries==1,"real post-proposal/final-fit seam reached exactly once");
    Require(observed.pldaEntries==0&&observed.vbxEntries==0,"cancellation must precede PLDA/VBx entry");
    Equal(observed.rows,finalRejected?std::vector<size_t>{2,3,4}:std::vector<size_t>{2,3,4,4},
          "no additional fit after proposal loop");
    Require(observed.labels.size()==observed.rows.size(),"all proposals completed before cancellation");
    EqualResult(published,sentinel);
    std::cout<<context<<" cancelled before PLDA/VBx, no returned result\n";
  }
}
void Errors() {
  // Initial fit and proposal fit are mandatory. A fault at either real entry
  // must propagate unchanged and may not publish even a partial result.
  for(size_t fit:{1,2}) {
    context="mandatory-fit-failure-"+std::to_string(fit);
    reuse_probe::Reset();reuse_probe::failFit=fit;
    community::ClusterResult published;published.hard={97531};const auto sentinel=published;
    bool threw=false;
    try {published=Run(Mixed());}catch(const std::bad_alloc&) {threw=true;}
    Require(threw&&reuse_probe::seen.rows.size()==fit,"mandatory fit-entry fault propagates");
    Require(reuse_probe::seen.labels.size()==fit-1,"no labels returned by failing fit");
    Require(reuse_probe::seen.pldaEntries==0&&reuse_probe::seen.vbxEntries==0,"failure precedes downstream");
    EqualResult(published,sentinel);
  }
  context="eliminated-final-fit-entry";
  auto x=TwoLong();reuse_probe::Reset();reuse_probe::failFit=2;
  bool oldThrows=false;
  try {(void)Run(x,true);}catch(const std::bad_alloc&) {oldThrows=true;}
  Require(oldThrows&&reuse_probe::seen.rows==std::vector<size_t>({2,2}),"baseline reaches redundant fit entry");
  reuse_probe::Reset();reuse_probe::failFit=2;
  auto result=Run(x);
  Equal(reuse_probe::seen.rows,std::vector<size_t>{2},"redundant final fit is not entered");
  auto expected=reference::Cluster(x.segments,x.embeddings,x.windows,MakePlda<community::Plda>(),
                                  x.cap,x.runs,x.ranges,x.rms);
  EqualResult(result,expected);
  context="real-ahc-error";reuse_probe::Reset();
  std::fill(x.runs.begin(),x.runs.end(),0.f);
  community::ClusterResult published;published.hard={97531};const auto sentinel=published;
  bool invalid=false;
  try {published=Run(x);}catch(const std::runtime_error& error) {
    invalid=std::string(error.what())=="Community clustering has no finite distance";
  }
  Require(invalid&&reuse_probe::seen.labels.empty(),"real algorithm error remains visible");
  Require(reuse_probe::seen.pldaEntries==0&&reuse_probe::seen.vbxEntries==0,"invalid fit not consumed");
  EqualResult(published,sentinel);
  std::cout<<"synthetic fit-entry faults propagated; redundant final fit omitted\n";
}
int main(int argc,char** argv) {
  try {
    const std::string mode=argc>1?argv[1]:"all";
    if(mode=="all"||mode=="no-short-cap")NoShortAndCap();
    if(mode=="all"||mode=="mixed")AcceptedRejected();
    if(mode=="all"||mode=="renumber")Renumbering();
    if(mode=="all"||mode=="empty-single-legacy")EmptySingleLegacy();
    if(mode=="all"||mode=="recovery")Recovery();
    if(mode=="all"||mode=="cancel")CancelSeam();
    if(mode=="all"||mode=="errors")Errors();
    std::cout<<"PASS "<<mode<<": "<<comparisons<<" dual-reference bitwise Cluster/turn comparisons\n";
    return 0;
  } catch(const std::exception& error) {
    std::cerr<<context<<": "<<error.what()<<'\n';return 1;
  }
}
'''


def source():
    helpers = parity.HARNESS.split('community::ClusterResult Check(', 1)[0]
    oracle = Path(__file__).with_name('community_ahc_reference.h')
    return ('#include "community_cluster.h"\n#include <sstream>\n'
            f'#include "{oracle.as_posix()}"\n#include "{FIXTURE.as_posix()}"\n'
            + parity.REFERENCE + helpers + HARNESS)


def compile_harness(directory, header=None):
    compiler = shutil.which('clang++') or shutil.which('g++')
    if compiler is None:
        raise AssertionError('C++17 compiler required for accepted-training regression')
    if header is None:
        header = (CPP / 'community_cluster.h').read_text()
    (directory / 'reuse_observer.h').write_text(OBSERVER)
    (directory / 'community_cluster.h').write_text(instrument(header))
    cpp = directory / 'reuse.cpp'
    cpp.write_text(source())
    binary = directory / 'reuse'
    subprocess.run([compiler, '-std=c++17', '-O2', '-I', str(directory), '-I', str(CPP),
                    str(cpp), '-o', str(binary)], check=True, timeout=60)
    return binary


class HarmonyCommunityAcceptedTrainingReuseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = compile_harness(Path(cls.directory.name))

    def run_case(self, mode):
        completed = subprocess.run([str(self.binary), mode], text=True,
                                   capture_output=True, timeout=60)
        print(completed.stdout, end='')
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn('PASS ' + mode, completed.stdout)

    def test_frozen_cluster_fixture_provenance(self):
        data = FIXTURE.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), FIXTURE_SHA256)
        block = data.decode().split('inline ClusterResult Cluster(', 1)[1]
        block = 'inline ClusterResult Cluster(' + block.rsplit('\n}  // namespace', 1)[0]
        self.assertEqual(hashlib.sha256(block.encode()).hexdigest(), CLUSTER_SHA256)

    def test_no_short_and_saturated_cap_remove_one_real_fit(self):
        self.run_case('no-short-cap')

    def test_accepted_and_rejected_proposals_preserve_full_training_labels(self):
        self.run_case('mixed')

    def test_accepted_proposal_renumbers_previous_rows(self):
        self.run_case('renumber')

    def test_empty_single_and_legacy_fields_and_fit_counts(self):
        self.run_case('empty-single-legacy')

    def test_short_recovery_and_long_vbx_partition_unchanged(self):
        self.run_case('recovery')

    def test_post_proposal_cancel_precedes_plda_and_vbx_entry(self):
        self.run_case('cancel')

    def test_mandatory_failures_propagate_without_publishing_result(self):
        self.run_case('errors')


if __name__ == '__main__':
    unittest.main()
