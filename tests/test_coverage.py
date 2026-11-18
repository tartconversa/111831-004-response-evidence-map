import unittest

from signal_lab.coverage import (
    CoverageStatus,
    CoverageStore,
    JudgmentCategory,
    assess_question,
    coverage_summary,
    find_candidate_responses,
)


def make_store():
    store = CoverageStore()
    store.add_observation("obs-1", "desk-1", "报道称关税上调推高进口成本")
    store.add_question(
        "q-1", "关税上调的原因是什么", asked_by="读者来信", observation_ids=("obs-1",)
    )
    store.add_response("r-1", "关税政策说明", "回应第一版：说明上调原因与依据")
    return store


class JudgmentTests(unittest.TestCase):
    def test_direct_judgment_marks_answered_and_exposes_basis(self):
        store = make_store()
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.DIRECT,
            "回应第一段正面解释了上调原因", "editor-a",
        )
        assessment = assess_question(store, "q-1")
        self.assertEqual(assessment.status, CoverageStatus.ANSWERED)
        self.assertEqual(assessment.observations[0].current.text, "报道称关税上调推高进口成本")
        item = assessment.judgments[0]
        self.assertTrue(item.effective)
        self.assertEqual(item.judgment.category, JudgmentCategory.DIRECT)
        self.assertEqual(item.judgment.rationale, "回应第一段正面解释了上调原因")
        self.assertEqual(item.judgment.editor, "editor-a")

    def test_topical_similarity_never_counts_as_answered(self):
        store = make_store()
        store.revise_response("r-1", "本文介绍关税政策的历史背景", note="改为背景介绍")
        candidates = find_candidate_responses(store, "q-1")
        self.assertTrue(candidates)  # 关键词重叠只产生待判断候选
        self.assertIn("关税", candidates[0].shared_terms)
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.TOPICAL,
            "只介绍背景，未解释原因", "editor-a",
        )
        assessment = assess_question(store, "q-1")
        self.assertEqual(assessment.status, CoverageStatus.UNANSWERED)
        summary = coverage_summary(store)
        self.assertEqual(summary.counts[CoverageStatus.ANSWERED], 0)
        self.assertEqual(summary.counts[CoverageStatus.UNANSWERED], 1)

    def test_partial_judgment_is_not_answered(self):
        store = make_store()
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.PARTIAL,
            "只解释了直接诱因，未说明决策背景", "editor-a",
        )
        assessment = assess_question(store, "q-1")
        self.assertEqual(assessment.status, CoverageStatus.PARTIALLY_ANSWERED)
        summary = coverage_summary(store)
        self.assertEqual(summary.counts[CoverageStatus.ANSWERED], 0)
        self.assertEqual(summary.counts[CoverageStatus.PARTIALLY_ANSWERED], 1)

    def test_judgment_requires_rationale_and_known_records(self):
        store = make_store()
        with self.assertRaises(ValueError):
            store.record_judgment(
                "j-1", "q-1", "r-1", JudgmentCategory.DIRECT, "  ", "editor-a"
            )
        with self.assertRaises(KeyError):
            store.record_judgment(
                "j-2", "q-x", "r-1", JudgmentCategory.DIRECT, "依据", "editor-a"
            )
        with self.assertRaises(KeyError):
            store.record_judgment(
                "j-3", "q-1", "r-x", JudgmentCategory.DIRECT, "依据", "editor-a"
            )


class ChangePropagationTests(unittest.TestCase):
    def test_revoked_judgment_stops_counting_but_stays_visible(self):
        store = make_store()
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.DIRECT, "正面解答", "editor-a"
        )
        self.assertEqual(assess_question(store, "q-1").status, CoverageStatus.ANSWERED)
        store.revoke_judgment("j-1", "复核后发现只回答了表层")
        assessment = assess_question(store, "q-1")
        self.assertEqual(assessment.status, CoverageStatus.UNANSWERED)
        item = assessment.judgments[0]
        self.assertFalse(item.judgment.active)
        self.assertFalse(item.effective)
        self.assertEqual(item.judgment.revoke_reason, "复核后发现只回答了表层")

    def test_response_revision_supersedes_earlier_judgment(self):
        store = make_store()
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.DIRECT, "正面解答", "editor-a"
        )
        store.revise_response("r-1", "回应第二版：删去原因说明，仅余背景", note="删改")
        assessment = assess_question(store, "q-1")
        self.assertEqual(assessment.status, CoverageStatus.UNANSWERED)
        item = assessment.judgments[0]
        self.assertTrue(item.stale)
        self.assertFalse(item.effective)
        self.assertEqual(item.judgment.response_version, 1)
        self.assertEqual(item.current_response_version, 2)
        store.record_judgment(
            "j-2", "q-1", "r-1", JudgmentCategory.DIRECT,
            "第二版补充说明后已正面解答", "editor-b",
        )
        self.assertEqual(assess_question(store, "q-1").status, CoverageStatus.ANSWERED)

    def test_observation_correction_updates_current_view(self):
        store = make_store()
        store.correct_observation("obs-1", "更正：关税未上调，系误读公告", "数据勘误")
        assessment = assess_question(store, "q-1")
        self.assertEqual(assessment.observations[0].current.text, "更正：关税未上调，系误读公告")
        self.assertEqual(assessment.observations[0].current.version, 2)
        self.assertEqual(assessment.observations[0].versions[0].text, "报道称关税上调推高进口成本")

    def test_withdrawn_observation_marks_question_unsupported(self):
        store = make_store()
        store.withdraw_observation("obs-1", "报道失实，整篇撤回")
        assessment = assess_question(store, "q-1")
        self.assertFalse(assessment.supported)
        self.assertTrue(assessment.observations[0].current.withdrawn)


class SummaryTests(unittest.TestCase):
    def test_summary_groups_questions_by_status(self):
        store = make_store()
        store.add_question("q-2", "补贴何时落地")
        store.add_question("q-3", "物流为何延误")
        store.add_question("q-4", "汇率影响几何")
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.DIRECT, "正面解答", "editor-a"
        )
        store.record_judgment(
            "j-2", "q-2", "r-1", JudgmentCategory.PARTIAL, "只答了一半", "editor-a"
        )
        store.record_judgment(
            "j-3", "q-3", "r-1", JudgmentCategory.TOPICAL, "仅主题相近", "editor-a"
        )
        summary = coverage_summary(store)
        self.assertEqual(summary.counts[CoverageStatus.ANSWERED], 1)
        self.assertEqual(summary.counts[CoverageStatus.PARTIALLY_ANSWERED], 1)
        self.assertEqual(summary.counts[CoverageStatus.UNANSWERED], 2)
        self.assertEqual(
            {item.question.question_id for item in summary.unanswered}, {"q-3", "q-4"}
        )


class RetrospectiveTests(unittest.TestCase):
    def test_retrospective_keeps_versions_and_judgments_frozen(self):
        store = make_store()
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.DIRECT, "正面解答", "editor-a"
        )
        retro = store.create_retrospective("retro-1", "十一月复盘")
        snapshot = retro.questions[0]
        self.assertEqual(snapshot.status, CoverageStatus.ANSWERED)

        store.correct_observation("obs-1", "更正后的观察文本", "数据勘误")
        store.revise_response("r-1", "回应第二版", note="补充背景")
        store.revoke_judgment("j-1", "回应改版后需重评")

        self.assertEqual(snapshot.question_text, "关税上调的原因是什么")
        self.assertEqual(snapshot.observations[0].text, "报道称关税上调推高进口成本")
        self.assertEqual(snapshot.observations[0].version, 1)
        self.assertEqual(snapshot.judgments[0].response_text, "回应第一版：说明上调原因与依据")
        self.assertFalse(snapshot.judgments[0].revoked)
        self.assertEqual(snapshot.judgments[0].rationale, "正面解答")
        self.assertEqual(snapshot.status, CoverageStatus.ANSWERED)

        current = assess_question(store, "q-1")
        self.assertEqual(current.status, CoverageStatus.UNANSWERED)
        self.assertEqual(current.observations[0].current.text, "更正后的观察文本")

    def test_retrospective_records_revoked_state_at_creation(self):
        store = make_store()
        store.record_judgment(
            "j-1", "q-1", "r-1", JudgmentCategory.DIRECT, "正面解答", "editor-a"
        )
        store.revoke_judgment("j-1", "依据不足")
        retro = store.create_retrospective("retro-1", "十一月复盘")
        snapshot = retro.questions[0]
        self.assertTrue(snapshot.judgments[0].revoked)
        self.assertEqual(snapshot.judgments[0].revoke_reason, "依据不足")
        self.assertEqual(snapshot.status, CoverageStatus.UNANSWERED)


if __name__ == "__main__":
    unittest.main()
