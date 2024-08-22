import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple, Union

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

HYPEROPT_FORMAT_ERROR_MESSAGE = (
    "Your response did not follow the required format\n"
    "```json\n"
    "{\n"
    "\t{'<model1_name>': [\n"
    "\t\t{'name': '<hyperparameter1_name>', 'type': '<type>', 'lb': <lower_bound>, 'ub': <upper_bound>, 'categories': [<categories>]},\n"
    "\t\t{'name': '<hyperparameter2_name>', 'type': '<type>', 'lb': <lower_bound>, 'ub': <upper_bound>, 'categories': [<categories>]},\n"
    " \t\tetc.\n"
    "\t],\n"
    "\t{'<model2_name>': [\n"
    "\t\t{'name': '<hyperparameter1_name>', 'type': '<type>', 'lb': <lower_bound>, 'ub': <upper_bound>, 'categories': [<categories>]},\n"
    "\t\t{'name': '<hyperparameter2_name>', 'type': '<type>', 'lb': <lower_bound>, 'ub': <upper_bound>, 'categories': [<categories>]},\n"
    " \t\tetc.\n"
    "\t],\n"
    "\tetc.\n"
    "}\n"
    "```\n"
    "Correct it now."
)


def strip_comments(code: str) -> str:
    # remove all single-line comments
    stripped_code = re.sub(r'#.*', '', code)

    # remove multi-line comments
    stripped_code = re.sub(r'\'\'\'(.*?)\'\'\'', '', stripped_code)
    stripped_code = re.sub(r'\"\"\"(.*?)\"\"\"', '', stripped_code)

    return stripped_code


def convert_to_single_line_blocks(code: str) -> List[str]:
    """Remove multi-line expressions from code and outputs list of single-line expressions.

    Args:
        code: string containing the code to convert

    Returns:
        blocks: list of single-line expressions
    """
    code = strip_comments(code)
    blocks = []
    code = code.split("\n")
    i = 0
    new_block = ""
    n_diff = 0
    while i < len(code):
        #         comment_ind = code[i].find("#") --> we should exclude the comments from the count...
        n_diff += code[i][:].count("(") - code[i].count(")")
        assert n_diff >= 0, (n_diff, code[i])
        new_block += re.sub(
            r'(\s([?,.!"]))|(?<=\[|\()(.*?)(?=\)|\])', lambda x: x.group().strip(), code[i]
        )  # remove space in parentheses
        if n_diff == 0:
            blocks.append(new_block)
            new_block = ""
            n_diff = 0
        i += 1
    assert n_diff == 0
    return blocks


def find_matching_parenthesis(line: str, start_ind: int, parenthesis_type: str, matching: str = None) -> int:
    """Returns the index of the closing parenthesis matching the opening parenthesis at index
    `start_ind`"""
    assert line[start_ind] == parenthesis_type
    if matching is None:
        parenthesis_pairs = ["()", "{}", "[]", "''", '""']
        matching = {p[0]: p[1] for p in parenthesis_pairs}[parenthesis_type]
    n_open = 1
    for i in range(start_ind + 1, len(line)):
        if line[i] == parenthesis_type:
            n_open += 1
        elif line[i] == matching:
            n_open -= 1
            if n_open == 0:
                return i
    raise IndexError(f"No matching opening parens at: {start_ind}")


def parse_function_call(func_call_str: str) -> List[Union[Tuple[str, str], str]]:
    """Extract positional arguments and kw argumens from a string corresponding to a function call.

    Args:
        func_call_str: string corresponding to a function call

    Example:
        >>> func_call = "f(x, asda, c={'as': '12'}, a=[1, 2], b='asd=,wd')"
        >>> print(parse_function_call(func_call))
    """
    tree = ast.parse(func_call_str)

    # The function call is the first element of the body
    func_call_node = tree.body[0].value

    # Fetch positional arguments names
    arg_list = [arg.id for arg in func_call_node.args]

    # The keywords are in the keywords attribute of the function call node
    keyword_list = [(keyword.arg, ast.literal_eval(keyword.value)) for keyword in func_call_node.keywords]

    return arg_list + keyword_list


def transform_args(args: List[Union[Tuple[str, str], str]], map_args: Dict[str, Any]) -> str:
    """Get string of argument assignment.

    Args:
        args: list of positional (str) / kw arguments (tuple of 2 strings)
        map_args: dictionary to map kw arguments

    Example:
        >>> func_call = "f(x, asda, c={'as': '12'}, a=[1, 2], b='asd=,wd')"
        >>> print(parse_function_call(func_call))
    """
    output = ""
    seen_args = set()

    def parse_arg(arg_: str) -> str:
        if not isinstance(arg_, str):
            return arg_
        return f"'{arg_}'"

    for arg in args:
        if not isinstance(arg, tuple):
            output += arg + ", "
        else:
            k = arg[0]
            if k not in map_args:
                output += f"{k}={parse_arg(arg[1])}, "
            else:
                seen_args.add(k)
                output += f"{k}={parse_arg(map_args[k])}, "

    for arg, arg_val in map_args.items():
        if arg in seen_args:
            continue
        output += f"{arg}={parse_arg(arg_val)}, "

    if output[-2:] == ", ":
        output = output[:-2]
    return output


def assign_hyperopt(code: str, candidate: pd.DataFrame, space: Dict[str, Dict[str, Any]]) -> str:
    """Modify a code to add hyperparameters.

    Args:
        code: original code without hyperparameters names
        space: dictionary corresponding to the hyperparameter space

    Returns:
        optimized_code: `code` with inserted candidate parameters
    """
    keyword_arguments = {}
    for model_name in space:
        keyword_arguments[model_name] = ", ".join([
            f'{param_dict["name"]}={candidate[model_name.lower() + "_" + param_dict["name"]]}'
            for param_dict in space[model_name]
        ])

    blocks = convert_to_single_line_blocks(code)

    optimized_code = ""
    for line in blocks:
        for model_name in space:
            pattern = f"{model_name}("
            ind = line.find(pattern)
            if ind != -1:
                end_ind = find_matching_parenthesis(line=line, start_ind=ind + len(pattern) - 1, parenthesis_type="(")
                line = line[:ind] + pattern + keyword_arguments[model_name] + line[end_ind:]
        optimized_code += line + "\n"

    return optimized_code


def wrap_code(code: str, space: Dict[str, Dict[str, Any]], cv_args: Dict[str, Any]) -> str:
    """Modify a code to add hyperparameters.

    Args:
        code: original code without hyperparameters names
        space: dictionary corresponding to the hyperparameter space

    Returns:
        blackbox_code: wrapped input `code` to make it a function of hyperparameters specified in the given `space`
    """
    arguments = {}
    arguments_str = ""
    keyword_arguments = {}
    keyword_arguments_str = ""
    for model_name in space:
        model_name_str = ''.join(model_name.lower().split()) + '_'
        arguments[model_name] = ", ".join([model_name_str + param_dict['name'] for param_dict in space[model_name]])
        arguments_str += arguments[model_name] + ", "
        keyword_arguments[model_name] = ", ".join([
            f"{param_dict['name']}={model_name_str}{param_dict['name']}" for param_dict in space[model_name]
        ])
        keyword_arguments_str += keyword_arguments[model_name] + ", "
    blocks = convert_to_single_line_blocks(code)
    arguments_str = arguments_str.lstrip().lstrip(',')
    blackbox_code = f"def blackbox({arguments_str}) -> float:\n"
    for line in blocks:
        for model_name in space:
            pattern = f"{model_name}("
            ind = line.find(pattern)
            if ind != -1:
                end_ind = find_matching_parenthesis(line=line, start_ind=ind + len(pattern) - 1, parenthesis_type="(")
                line = line[:ind] + pattern + keyword_arguments[model_name] + line[end_ind:]
        blackbox_code += "\t" + line + "\n"

    metric_value_direction = cv_args.pop('metric_value_direction')
    k_folds_cv_line = "\tfrom utils import k_folds_cv\n"
    k_folds_cv_line += "\tscore = k_folds_cv(" + ', '.join([k + "=" + str(v) for k, v in cv_args.items()]) + ")\n"
    blackbox_code += k_folds_cv_line
    if metric_value_direction == "MAX":
        blackbox_code += "\tscore = 1.0 - score\n"

    blackbox_code += "\treturn score"
    return blackbox_code


def unwrap_code(wrapped_code_lines: list[str]) -> str:
    """
    Removes the function definition and return statement and de-indents all code.
    Note: this takes in the blackbox function code as a list of lines (simpler), so read the code
    in the following way before passing the lines to this function:
    >>> with open('path/to/blackbox.py', 'r') as f:
    >>>     bbox_lines = f.readlines()
    >>> unwrap_code(wrapped_code_lines=bbox_lines)
    """
    # function_definition, body = wrapped_code.split(":\n", 1)
    # body, return_statement = body.split("\nreturn", 1)
    # return body.strip()
    body_lines = wrapped_code_lines[1:-1]
    unindented_lines = [l.split("\t")[1] for l in body_lines]
    return "".join(unindented_lines)


def format_f_inputs(
        x: pd.DataFrame, param_space_with_model: Dict[str, Dict[str, List[Any]]]
) -> List[Dict[str, Any]]:
    formatted_inputs = []
    for i in range(len(x)):
        new_input = {}
        for function_param_name, ind in x.iloc[i].to_dict().items():
            function, param_name = function_param_name.split("__")
            if function not in new_input:
                new_input[function] = {}
            new_input[function][param_name] = param_space_with_model[function][param_name][ind]
        formatted_inputs.append(new_input)
    return formatted_inputs


def k_folds_cv(model, X: pd.DataFrame, y: pd.DataFrame, metric_func):
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = []

    if isinstance(X, np.ndarray):
        X = pd.DataFrame(X)
    if isinstance(y, np.ndarray):
        y = pd.DataFrame(y)

    for fold_i, (train_index, valid_index) in enumerate(cv.split(X, y)):
        X_train, y_train = X.iloc[train_index], y.iloc[train_index]
        X_valid, y_valid = X.iloc[valid_index], y.iloc[valid_index]

        model.fit(X_train, y_train)
        y_pred = model.predict(X_valid)

        score = metric_func(y_valid, y_pred)
        scores.append(score)

        print(f"FOLD {fold_i} Done. Score : {score}")

    mean_score = np.mean(scores)
    return mean_score


def create_experiment_full_optimization_trajectory(reflection_experiment_dir: Path) -> None:
    """
    From the experiment dir, for each seed find all search spaces and gather them into,
    one overall trajectory.

    reflection_experiment_dir: path to the workspace/competition-name/reflection-strategy
    """
    # if "no_reflection" == experiment_dir.name:
    overall_results = pd.DataFrame()
    trajectories = []
    for seed in reflection_experiment_dir.iterdir():
        if seed.is_file():
            continue
        for search_space in sorted(list(seed.iterdir())):
            if search_space.name == "logs":
                continue
            if search_space.is_file():
                continue
            if (search_space / 'optimization_trajectory.csv').exists():
                traj = pd.read_csv(search_space / 'optimization_trajectory.csv')
                trajectories.append(traj)
        overall_results = overall_results._append(trajectories)
        overall_results.to_csv(seed / "full_optimization_trajectory.csv")
        print(f"created {seed / 'full_optimization_trajectory.csv'}", flush=True)


def create_experiment_report(experiment_dir: Path) -> None:
    """
    From the experiment dir, create an overall trajectory per seed, and gather all seeds into
    one SCORE csv file to be used in a plot

    experiment_dir: path to the workspace/competition-name
    """
    if 'results' not in experiment_dir.name:
        experiment_dir = experiment_dir / 'results'

    report = pd.DataFrame([])
    for reflection_strategy in experiment_dir.iterdir():
        if reflection_strategy.is_file():
            continue
        overall_results = pd.DataFrame([])
        create_experiment_full_optimization_trajectory(reflection_experiment_dir=reflection_strategy)
        for seed in reflection_strategy.iterdir():
            if seed.is_file():
                continue
            traj = pd.read_csv(seed / 'full_optimization_trajectory.csv')
            traj = traj.reset_index(drop=True)
            overall_results[seed.name] = traj['y']
        overall_results.to_csv(reflection_strategy / 'full_optimization_trajectories.csv')


def plot_results(experiment_dir: Path) -> None:
    """
    :param experiment_dir: path to the workspace/competition-name
    """
    create_experiment_report(experiment_dir=experiment_dir)

    for reflection_strategy in experiment_dir.iterdir():
        if reflection_strategy.is_dir():
            results = pd.read_csv(reflection_strategy / 'full_optimization_trajectories.csv', index_col=0)
            results['mean'] = results.mean(axis=1)
            results['std'] = results.std(axis=1)
            plt.plot(results['mean'], label=reflection_strategy.name)
            plt.fill_between(
                np.arange(len(results['mean'])),
                results['mean'] + results['std'],
                results['mean'] - results['std'],
                alpha=0.2
            )
    plt.legend()
    plt.title(experiment_dir.parent.name)
    plt.savefig(experiment_dir / 'full_optimization_trajectories.png')
    plt.close()
