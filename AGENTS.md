# Project constraints

- The current specification is `../课程个性化学习智能体_项目搭建方案_v7_20261008.docx`.
- Develop in this independent repository. Do not add features to the original ChatEval repository.
- PLIAC is the platform repository. `src/learning_agent` provides knowledge, assets and evidence/diagnosis; `src/pliac` provides the learning workspace and orchestration. Preserve the legacy app import and existing runtime paths.
- Current workspace scope includes rule-based lessons, learner answers, human review, chapter-policy reports and evidence handbooks. Distinguish this from live-model teaching, executable training, recordings and complete platform acceptance.
- Keep draft content separate from published content. Never manufacture human review, real learner records or live-model validation.
- The immutable `ml_acceptance_demo` course is a separate, explicitly marked acceptance fixture. Its objective questions use server-side `demo-choice-v1` rules and `rule_verified` diagnoses, never fabricated human review. Formal courses retain their existing publication and review requirements.
- Preserve raw evidence separately from diagnoses and derived learner state. System completion, model inference, interests and auxiliary behavioral/emotional clues cannot independently prove mastery.
- Only prerequisite edges constrain order. Confusable and related relations are non-directional for learning order.
- Use UTF-8 and pathlib; store runtime data under outputs and test in isolated temporary directories.
