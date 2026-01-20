"""
Model Configuration Loader

Single source of truth for AI model selection.
Loads validated models from vision_models.yaml and provides task-based model selection.
"""

import os
import yaml
from typing import Dict, Optional, List
from pathlib import Path


class ModelConfig:
    """Centralized model configuration manager"""

    def __init__(self, config_path: str = None):
        """Load model configuration from YAML"""
        if config_path is None:
            # Default to config/vision_models.yaml relative to this file
            config_dir = Path(__file__).parent
            config_path = config_dir / "vision_models.yaml"

        self.config_path = Path(config_path)
        self.providers = {}
        self.task_assignments = {}
        self.models_by_id = {}

        self._load_config()

    def _load_config(self):
        """Load and parse the YAML configuration"""
        if not self.config_path.exists():
            print(f"[ModelConfig] WARNING: Config not found at {self.config_path}")
            return

        with open(self.config_path, 'r') as f:
            config = yaml.safe_load(f)

        self.providers = config.get('providers', {})
        self.task_assignments = config.get('task_assignments', {})

        # Build lookup table of all models by ID
        for provider_key, provider_data in self.providers.items():
            for model in provider_data.get('models', []):
                model_id = model.get('id')
                if model_id:
                    self.models_by_id[model_id] = {
                        **model,
                        'provider': provider_key,
                        'env_key': provider_data.get('env_key')
                    }

        print(f"[ModelConfig] Loaded {len(self.models_by_id)} models from {len(self.providers)} providers")

    def get_model_for_task(self, task: str, tier_preference: str = None) -> Dict:
        """
        Get the appropriate model for a task.

        Args:
            task: Task type (e.g., 'content_generation', 'research_enrichment', 'image_analysis')
            tier_preference: Optional tier override ('economy', 'standard', 'frontier')

        Returns:
            Model configuration dict with id, provider, and settings
        """
        task_config = self.task_assignments.get(task, {})

        if not task_config:
            print(f"[ModelConfig] WARNING: No assignment for task '{task}', using default")
            # Fallback to a safe default
            return self.get_model_by_id('gpt-4o-mini') or {'id': 'gpt-4o-mini', 'provider': 'openai'}

        # Get primary model
        model_id = task_config.get('model')

        # If tier preference specified and different tier model available
        if tier_preference and tier_preference != task_config.get('tier'):
            alt_model = task_config.get(f'{tier_preference}_alternative')
            if alt_model:
                model_id = alt_model

        model = self.get_model_by_id(model_id)

        if not model:
            # Try fallback
            fallback_id = task_config.get('fallback')
            if fallback_id:
                model = self.get_model_by_id(fallback_id)
                print(f"[ModelConfig] Using fallback {fallback_id} for task '{task}'")

        if not model:
            print(f"[ModelConfig] ERROR: No valid model found for task '{task}'")
            return {'id': model_id, 'provider': 'unknown'}

        # Add task-specific settings
        model['task'] = task
        model['max_tokens_param'] = self._get_max_tokens_param(model['id'])

        return model

    def get_model_by_id(self, model_id: str) -> Optional[Dict]:
        """Get model configuration by its ID"""
        return self.models_by_id.get(model_id)

    def get_active_models(self, provider: str = None, tier: str = None) -> List[Dict]:
        """Get all active (validated) models, optionally filtered"""
        models = []
        for model_id, model in self.models_by_id.items():
            if model.get('status') != 'active':
                continue
            if provider and model.get('provider') != provider:
                continue
            if tier and model.get('tier') != tier:
                continue
            models.append(model)
        return models

    def _get_max_tokens_param(self, model_id: str) -> str:
        """
        Determine the correct max tokens parameter name for a model.
        GPT-5.x uses max_completion_tokens, others use max_tokens.
        """
        if model_id.startswith('gpt-5'):
            return 'max_completion_tokens'
        return 'max_tokens'

    def get_provider_for_model(self, model_id: str) -> str:
        """Get the provider name for a model"""
        model = self.models_by_id.get(model_id)
        return model.get('provider') if model else None

    def get_env_key_for_model(self, model_id: str) -> str:
        """Get the environment variable key for a model's API key"""
        model = self.models_by_id.get(model_id)
        return model.get('env_key') if model else None


# Global singleton instance
_config_instance = None


def get_model_config() -> ModelConfig:
    """Get the global ModelConfig instance"""
    global _config_instance
    if _config_instance is None:
        _config_instance = ModelConfig()
    return _config_instance


def get_model_for_task(task: str, tier_preference: str = None) -> Dict:
    """Convenience function to get model for a task"""
    return get_model_config().get_model_for_task(task, tier_preference)


def get_model_id_for_task(task: str, tier_preference: str = None) -> str:
    """Convenience function to get just the model ID for a task"""
    return get_model_for_task(task, tier_preference).get('id')
