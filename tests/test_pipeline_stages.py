# -*- coding: utf-8 -*-
"""
Unit tests for the SOLID 5-Core-Phase Pipeline Stages.
Verifies interfaces, phase execution wrappers, and backward compatibility.
"""

import unittest
from pipeline.interfaces import IStage, IEpisodeProcessor
from pipeline.stages import (
    Phase1_VisualPrep,
    Phase2_AIScripting,
    Phase3_VoiceSubtitles,
    Phase4_EpisodeRender,
    Phase5_FinalExport,
    Stage1_VisualPrep,
    Stage2_AIScripting,
    Stage3_VoiceSubtitles,
    Stage4_EpisodeRender,
    Stage5_FinalExport,
    execute_single_episode_visual,
    execute_single_episode_script,
    execute_single_episode_audio,
    execute_single_episode_render
)


class TestPipelineStages(unittest.TestCase):
    def test_stage_interfaces(self):
        """Ensure all 5 phases implement IStage."""
        p1 = Phase1_VisualPrep()
        p2 = Phase2_AIScripting()
        p3 = Phase3_VoiceSubtitles()
        p4 = Phase4_EpisodeRender()
        p5 = Phase5_FinalExport()

        self.assertIsInstance(p1, IStage)
        self.assertIsInstance(p2, IStage)
        self.assertIsInstance(p3, IStage)
        self.assertIsInstance(p4, IStage)
        self.assertIsInstance(p5, IStage)

    def test_episode_processor_interfaces(self):
        """Ensure streaming episode phases implement IEpisodeProcessor."""
        p1 = Phase1_VisualPrep()
        p2 = Phase2_AIScripting()
        p3 = Phase3_VoiceSubtitles()
        p4 = Phase4_EpisodeRender()

        self.assertIsInstance(p1, IEpisodeProcessor)
        self.assertIsInstance(p2, IEpisodeProcessor)
        self.assertIsInstance(p3, IEpisodeProcessor)
        self.assertIsInstance(p4, IEpisodeProcessor)

    def test_stage_weights(self):
        """Check phase weights are positive numbers."""
        p1 = Phase1_VisualPrep()
        p2 = Phase2_AIScripting()
        p3 = Phase3_VoiceSubtitles()
        p4 = Phase4_EpisodeRender()
        p5 = Phase5_FinalExport()

        self.assertGreater(p1.weight, 0.0)
        self.assertGreater(p2.weight, 0.0)
        self.assertGreater(p3.weight, 0.0)
        self.assertGreater(p4.weight, 0.0)
        self.assertGreater(p5.weight, 0.0)

    def test_aliases(self):
        """Check backward compatibility aliases match."""
        self.assertIs(Stage1_VisualPrep, Phase1_VisualPrep)
        self.assertIs(Stage2_AIScripting, Phase2_AIScripting)
        self.assertIs(Stage3_VoiceSubtitles, Phase3_VoiceSubtitles)
        self.assertIs(Stage4_EpisodeRender, Phase4_EpisodeRender)
        self.assertIs(Stage5_FinalExport, Phase5_FinalExport)

    def test_functions_callable(self):
        """Check episode executor coroutine functions exist and are callable."""
        self.assertTrue(callable(execute_single_episode_visual))
        self.assertTrue(callable(execute_single_episode_script))
        self.assertTrue(callable(execute_single_episode_audio))
        self.assertTrue(callable(execute_single_episode_render))


if __name__ == "__main__":
    unittest.main()
