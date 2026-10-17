from typing import Any, TypeVar

from pydantic import BaseModel, ValidationInfo

InputModel = TypeVar("InputModel", bound=BaseModel)
Rules = TypeVar("Rules")
_RULES = "rules"


def parse_input(model: type[InputModel], data: dict[str, Any], rules: object) -> InputModel:
    # Las reglas salen de la configuración, así que llegan a los validadores por el contexto y no como constantes
    return model.model_validate(data, context={_RULES: rules})


def rules_of(info: ValidationInfo, rules_type: type[Rules]) -> Rules:
    rules = info.context[_RULES]
    if not isinstance(rules, rules_type):
        raise TypeError(f"Expected {rules_type.__name__} in the validation context")
    return rules
