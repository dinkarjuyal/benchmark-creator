"""Pandas behavioral injection library for the counterfactual curriculum benchmark.

Each entry describes:
  - A single-parameter change to a pandas function signature or default
  - A short executable snippet whose output changes after the patch
  - The pre-patch output (used as hard-negative distractor A)
  - The post-patch correct output (answer B, position randomized at generation time)
  - Two additional misconception distractors (C, D)

correct_output and original_output have been verified against pandas 2.2.x.
"""
from __future__ import annotations

PANDAS_INJECTIONS: list[dict] = [

    # ------------------------------------------------------------------ sort_order
    {
        "task_id": "groupby_sort_false",
        "family": "sort_order",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "groupby sort=True→False changes group key iteration order",
        "source_file": "pandas/core/groupby/groupby.py",
        "source_excerpt": (
            "class GroupBy:\n"
            "    def __init__(self, obj, keys=None, ..., sort: bool = True, ...):\n"
            "        ...\n"
            "        self.sort = sort\n"
            "    # sort=True means group keys are sorted before aggregation\n"
            "    # sort=False means group keys appear in first-occurrence order\n"
        ),
        "find": "sort: bool = True",
        "replace": "sort: bool = False",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'k': [3, 1, 2, 1], 'v': [10, 20, 30, 40]})\n"
            "print(list(df.groupby('k').groups.keys()))\n"
        ),
        "original_output": "[1, 2, 3]",
        "correct_output": "[3, 1, 2]",
        "distractors": [
            {"text": "[1, 2, 3]", "type": "hard_negative", "explanation": "Original sorted behavior — agent missed effect of sort=False"},
            {"text": "[3, 1, 2]", "type": "correct", "explanation": "First-occurrence order: 3 appears first, then 1, then 2"},
            {"text": "[1, 1, 2, 3]", "type": "plausible_misconception", "explanation": "Groups.keys() returns unique keys, not all values"},
            {"text": "Raises ValueError", "type": "exception_distractor", "explanation": "sort=False is a valid parameter, raises nothing"},
        ],
        "correct_id": "B",
        "explanation": (
            "sort=False causes groupby to preserve first-occurrence order of group keys. "
            "Key 3 appears first in the DataFrame (row 0), then 1 (row 1), then 2 (row 2)."
        ),
        "curriculum_note": "Level 1: single-parameter, immediate output change.",
        "is_hard_negative": False,
    },

    {
        "task_id": "value_counts_sort_false",
        "family": "sort_order",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "value_counts sort=True→False changes output ordering from count-desc to first-occurrence",
        "source_file": "pandas/core/base.py",
        "source_excerpt": (
            "def value_counts(self, normalize=False, sort=True, ascending=False, ...):\n"
            "    \"\"\"Return object containing counts of unique values.\n"
            "    sort : bool, default True\n"
            "        Sort by frequencies. When False, the result is in order\n"
            "        of first occurrence.\n"
            "    \"\"\"\n"
        ),
        "find": "sort=True",
        "replace": "sort=False",
        "snippet": (
            "import pandas as pd\n"
            "s = pd.Series(['b', 'a', 'a', 'a', 'b', 'c'])\n"
            "print(list(s.value_counts().index))\n"
        ),
        "original_output": "['a', 'b', 'c']",
        "correct_output": "['b', 'a', 'c']",
        "distractors": [
            {"text": "['a', 'b', 'c']", "type": "hard_negative", "explanation": "Original: sorted by count desc (a=3, b=2, c=1)"},
            {"text": "['b', 'a', 'c']", "type": "correct", "explanation": "First-occurrence order: b at index 0, a at index 1, c at index 3"},
            {"text": "['a', 'b', 'c'] (sorted alphabetically)", "type": "plausible_misconception", "explanation": "sort=False is not alphabetical — it is first-occurrence"},
            {"text": "['c', 'b', 'a']", "type": "plausible_misconception", "explanation": "Ascending count order, but ascending= parameter controls this, not sort="},
        ],
        "correct_id": "B",
        "explanation": (
            "sort=False returns values in first-occurrence order: 'b' appears first (index 0), "
            "'a' appears second (index 1), 'c' appears last (index 3)."
        ),
        "curriculum_note": "Level 1. Common trap: sort=False is not alphabetical order.",
        "is_hard_negative": False,
    },

    {
        "task_id": "sort_values_na_last",
        "family": "sort_order",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "sort_values na_position='last'→'first' moves NaN to front",
        "source_file": "pandas/core/frame.py",
        "source_excerpt": (
            "def sort_values(self, by, axis=0, ascending=True,\n"
            "                na_position='last', ...):\n"
            "    \"\"\"na_position : {'first', 'last'}, default 'last'\n"
            "        Puts NaNs at the beginning if 'first'; 'last' puts NaNs at the end.\n"
            "    \"\"\"\n"
        ),
        "find": "na_position='last'",
        "replace": "na_position='first'",
        "snippet": (
            "import pandas as pd, numpy as np\n"
            "s = pd.Series([3.0, 1.0, np.nan, 2.0])\n"
            "print(list(s.sort_values()))\n"
        ),
        "original_output": "[1.0, 2.0, 3.0, nan]",
        "correct_output": "[nan, 1.0, 2.0, 3.0]",
        "distractors": [
            {"text": "[1.0, 2.0, 3.0, nan]", "type": "hard_negative", "explanation": "Original: NaN at end (na_position='last')"},
            {"text": "[nan, 1.0, 2.0, 3.0]", "type": "correct", "explanation": "na_position='first' puts NaN before sorted values"},
            {"text": "[nan, 3.0, 2.0, 1.0]", "type": "plausible_misconception", "explanation": "Confuses na_position with ascending; values are still ascending"},
            {"text": "Raises TypeError: cannot compare NaN", "type": "exception_distractor", "explanation": "pandas handles NaN in sort without raising"},
        ],
        "correct_id": "B",
        "explanation": "na_position='first' places NaN values before the sorted non-NaN values. Sorting order of non-NaN values is unchanged.",
        "curriculum_note": "Level 1. Clean single-parameter, unambiguous output change.",
        "is_hard_negative": False,
    },

    # ------------------------------------------------------------------ nan_semantics
    {
        "task_id": "groupby_dropna_false",
        "family": "nan_semantics",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "groupby dropna=True→False includes NaN as a group key",
        "source_file": "pandas/core/groupby/groupby.py",
        "source_excerpt": (
            "class GroupBy:\n"
            "    def __init__(self, obj, keys=None, ..., dropna: bool = True, ...):\n"
            "        \"\"\"dropna : bool, default True\n"
            "            If True, and if group keys contain NA values, NA values\n"
            "            together with row/column will be dropped.\n"
            "        \"\"\"\n"
        ),
        "find": "dropna: bool = True",
        "replace": "dropna: bool = False",
        "snippet": (
            "import pandas as pd, numpy as np\n"
            "df = pd.DataFrame({'k': [1.0, 2.0, None, 1.0], 'v': [10, 20, 30, 40]})\n"
            "result = df.groupby('k')['v'].sum()\n"
            "print(len(result), sorted(result.index, key=lambda x: (x != x, x)))\n"
        ),
        "original_output": "2 [1.0, 2.0]",
        "correct_output": "3 [1.0, 2.0, nan]",
        "distractors": [
            {"text": "2 [1.0, 2.0]", "type": "hard_negative", "explanation": "Original: NaN group dropped (dropna=True)"},
            {"text": "3 [1.0, 2.0, nan]", "type": "correct", "explanation": "dropna=False includes NaN as group key; NaN row (value=30) forms its own group"},
            {"text": "4 [1.0, 1.0, 2.0, nan]", "type": "plausible_misconception", "explanation": "Groups are unique keys, not individual rows"},
            {"text": "3 [1.0, 2.0, 0]", "type": "plausible_misconception", "explanation": "None is not coerced to 0 — it remains NaN as a group key"},
        ],
        "correct_id": "B",
        "explanation": (
            "With dropna=False, rows with NaN keys are not dropped — they form their own group "
            "(key=NaN). The sum for that group is 30 (the single row where k=None)."
        ),
        "curriculum_note": "Level 2: requires understanding that the NaN row has value 30 (not dropped).",
        "is_hard_negative": False,
    },

    {
        "task_id": "skipna_false_mean",
        "family": "nan_semantics",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "Series.mean(skipna=True) → skipna=False propagates NaN instead of ignoring it",
        "source_file": "pandas/core/nanops.py",
        "source_excerpt": (
            "def nanmean(values, axis=None, skipna=True, ...):\n"
            "    \"\"\"skipna : bool, default True\n"
            "        Exclude NA/null values when computing the result.\n"
            "        If the entire Series is NA, the result will be NA.\n"
            "    \"\"\"\n"
            "    if not skipna:\n"
            "        if np.any(np.isnan(values)):\n"
            "            return np.nan\n"
        ),
        "find": "skipna=True",
        "replace": "skipna=False",
        "snippet": (
            "import pandas as pd, numpy as np\n"
            "s = pd.Series([1.0, 2.0, np.nan, 4.0])\n"
            "print(s.mean())\n"
        ),
        "original_output": "2.3333333333333335",
        "correct_output": "nan",
        "distractors": [
            {"text": "2.3333333333333335", "type": "hard_negative", "explanation": "Original: NaN skipped, mean of [1, 2, 4] = 7/3"},
            {"text": "nan", "type": "correct", "explanation": "skipna=False: any NaN in input propagates to output"},
            {"text": "1.75", "type": "plausible_misconception", "explanation": "Treating NaN as 0: mean of [1, 2, 0, 4] = 7/4 — but pandas doesn't do this"},
            {"text": "Raises ValueError: cannot compute mean with NaN", "type": "exception_distractor", "explanation": "pandas returns nan, does not raise"},
        ],
        "correct_id": "B",
        "explanation": "skipna=False causes any NaN in the input to propagate: the result is NaN rather than the mean of the non-NaN values.",
        "curriculum_note": "Level 1. Classic NaN propagation vs NaN skipping distinction.",
        "is_hard_negative": False,
    },

    {
        "task_id": "fillna_method_bfill",
        "family": "nan_semantics",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "fillna ffill→bfill changes direction of forward/backward fill",
        "source_file": "pandas/core/generic.py",
        "source_excerpt": (
            "def fillna(self, value=None, method=None, ...):\n"
            "    \"\"\"method : {'backfill', 'bfill', 'pad', 'ffill', None}, default None\n"
            "        Method to use for filling holes in reindexed Series.\n"
            "        pad/ffill: propagate last valid observation forward.\n"
            "        backfill/bfill: use next valid observation to fill gap.\n"
            "    \"\"\"\n"
        ),
        "find": "method='ffill'",
        "replace": "method='bfill'",
        "snippet": (
            "import pandas as pd, numpy as np\n"
            "s = pd.Series([1.0, np.nan, np.nan, 4.0])\n"
            "print(list(s.fillna(method='ffill')))\n"
        ),
        "original_output": "[1.0, 1.0, 1.0, 4.0]",
        "correct_output": "[1.0, 4.0, 4.0, 4.0]",
        "distractors": [
            {"text": "[1.0, 1.0, 1.0, 4.0]", "type": "hard_negative", "explanation": "Original ffill: propagates 1.0 forward into the NaN gaps"},
            {"text": "[1.0, 4.0, 4.0, 4.0]", "type": "correct", "explanation": "bfill: propagates 4.0 backward into the NaN gaps"},
            {"text": "[1.0, 2.5, 2.5, 4.0]", "type": "plausible_misconception", "explanation": "Linear interpolation — not what bfill does"},
            {"text": "[1.0, nan, nan, 4.0]", "type": "plausible_misconception", "explanation": "bfill does fill the gaps — they become 4.0"},
        ],
        "correct_id": "B",
        "explanation": "bfill (backward fill) uses the next valid observation to fill gaps. The NaN at index 1 and 2 are filled with 4.0 (the next valid value).",
        "curriculum_note": "Level 1. Directional fill — forward vs backward.",
        "is_hard_negative": False,
    },

    # ------------------------------------------------------------------ dtype_coercion
    {
        "task_id": "nullable_int_coercion",
        "family": "dtype_coercion",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "Int64 (nullable) vs int64 (numpy): None silently promotes to float64",
        "source_file": "pandas/core/arrays/masked.py",
        "source_excerpt": (
            "# pandas provides two integer dtypes:\n"
            "# 'int64'  — NumPy integer. Cannot hold NA; None/NaN causes upcast to float64.\n"
            "# 'Int64'  — Pandas nullable integer. Holds NA as pd.NA without losing int semantics.\n"
            "#\n"
            "# When dtype='int64' and None is in the data:\n"
            "    # pandas upcasts the entire array to float64 to represent NaN.\n"
        ),
        "find": "dtype='Int64'",
        "replace": "dtype='int64'",
        "snippet": (
            "import pandas as pd\n"
            "s = pd.Series([1, 2, None], dtype='Int64')\n"
            "print(s.dtype, repr(s[2]))\n"
        ),
        "original_output": "Int64 <NA>",
        "correct_output": "float64 nan",
        "distractors": [
            {"text": "Int64 <NA>", "type": "hard_negative", "explanation": "Original nullable Int64 preserves integer type and uses pd.NA"},
            {"text": "float64 nan", "type": "correct", "explanation": "numpy int64 can't hold None; pandas silently promotes to float64, None becomes float nan"},
            {"text": "int64 0", "type": "plausible_misconception", "explanation": "None is not coerced to 0 in pandas — it becomes NaN (which forces float upcast)"},
            {"text": "Raises TypeError: cannot convert None to int", "type": "exception_distractor", "explanation": "pandas silently upcasts rather than raising"},
        ],
        "correct_id": "B",
        "explanation": (
            "NumPy int64 arrays cannot hold NA values. When None is present, pandas silently "
            "upcasts the entire array to float64, converting None to float nan. "
            "This is the classic 'integer NaN gotcha' in pandas."
        ),
        "curriculum_note": "Level 2. The silent float upcast is one of the most common pandas gotchas.",
        "is_hard_negative": False,
    },

    {
        "task_id": "categorical_observed_false",
        "family": "dtype_coercion",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "groupby observed=True→False includes unobserved Categorical categories",
        "source_file": "pandas/core/groupby/groupby.py",
        "source_excerpt": (
            "def __init__(self, ..., observed: bool = True, ...):\n"
            "    \"\"\"observed : bool, default True (changed from False in pandas 2.2)\n"
            "        Only relevant for Categorical groupers.\n"
            "        If True: only show observed values for categorical groupers.\n"
            "        If False: show all values for categorical groupers.\n"
            "    \"\"\"\n"
        ),
        "find": "observed: bool = True",
        "replace": "observed: bool = False",
        "snippet": (
            "import pandas as pd\n"
            "cat = pd.Categorical(['a', 'a', 'b'], categories=['a', 'b', 'c'])\n"
            "df = pd.DataFrame({'k': cat, 'v': [1, 2, 3]})\n"
            "result = df.groupby('k')['v'].sum()\n"
            "print(list(result.index))\n"
        ),
        "original_output": "['a', 'b']",
        "correct_output": "['a', 'b', 'c']",
        "distractors": [
            {"text": "['a', 'b']", "type": "hard_negative", "explanation": "observed=True (default since 2.2): only categories actually present in data"},
            {"text": "['a', 'b', 'c']", "type": "correct", "explanation": "observed=False: all Categorical categories appear, even if unobserved; 'c' gets sum=0"},
            {"text": "['a', 'b', 'c', nan]", "type": "plausible_misconception", "explanation": "Categorical doesn't add a NaN group; only defined categories appear"},
            {"text": "Raises CategoricalError", "type": "exception_distractor", "explanation": "observed=False is valid — it was the old default before pandas 2.2"},
        ],
        "correct_id": "B",
        "explanation": (
            "observed=False causes all Categorical categories to appear in the result, "
            "including 'c' which has no data (its sum will be 0). "
            "This was the default before pandas 2.2 — a version-sensitive gotcha."
        ),
        "curriculum_note": "Level 2. Version-sensitive: behavior changed in pandas 2.2. Tests whether agent knows Categorical semantics.",
        "is_hard_negative": False,
    },

    {
        "task_id": "loc_scalar_dtype_coercion",
        "family": "dtype_coercion",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": ".loc with scalar row key coerces mixed-dtype row to common dtype",
        "source_file": "pandas/core/indexing.py",
        "source_excerpt": (
            "# When df.loc[scalar] selects a single row, the result is a Series.\n"
            "# Mixed-dtype columns (e.g., int + float) are coerced to a common dtype.\n"
            "# df.loc[[scalar]] (list) returns a DataFrame and preserves column dtypes.\n"
            "#\n"
            "# _LocIndexer._getitem_axis:\n"
            "    # scalar key → calls _get_label → returns Series (coercion happens here)\n"
            "    # list key   → calls _getitem_axis with list → returns DataFrame\n"
        ),
        "find": "df.loc[0]          # scalar — returns Series with dtype coercion",
        "replace": "df.loc[[0]]        # list   — returns DataFrame, preserves dtypes",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'a': [1, 2], 'b': [1.5, 2.5]})\n"
            "row = df.loc[0]\n"
            "print(type(row['a']).__name__, row['a'])\n"
        ),
        "original_output": "float64 1.0",
        "correct_output": "int64 1",
        "distractors": [
            {"text": "float64 1.0", "type": "hard_negative", "explanation": "Scalar .loc coerces to common dtype (float, since column b is float); a becomes 1.0"},
            {"text": "int64 1", "type": "correct", "explanation": "List .loc returns DataFrame; row['a'] is a Series of int64, row['a'].iloc[0] preserves int64"},
            {"text": "int 1", "type": "plausible_misconception", "explanation": "Pandas uses numpy int64, not Python int"},
            {"text": "object 1", "type": "plausible_misconception", "explanation": "Object dtype is for strings/mixed; int64 columns stay int64 in DataFrame selection"},
        ],
        "correct_id": "B",
        "explanation": (
            "df.loc[0] (scalar) returns a Series where all values are cast to a common dtype — "
            "the int column 'a' becomes float 1.0 because 'b' is float. "
            "df.loc[[0]] (list) returns a DataFrame, preserving each column's own dtype."
        ),
        "curriculum_note": "Level 2. Scalar vs list .loc is one of the trickiest pandas type preservation issues.",
        "is_hard_negative": False,
    },

    # ------------------------------------------------------------------ index_alignment
    {
        "task_id": "merge_how_outer",
        "family": "index_alignment",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "merge how='inner'→'outer' changes row count for non-matching keys",
        "source_file": "pandas/core/reshape/merge.py",
        "source_excerpt": (
            "def merge(left, right, how='inner', on=None, ...):\n"
            "    \"\"\"how : {'left', 'right', 'outer', 'inner', 'cross'}, default 'inner'\n"
            "        Type of merge to be performed.\n"
            "        inner: use intersection of keys from both frames (SQL inner join).\n"
            "        outer: use union of keys from both frames (SQL full outer join).\n"
            "    \"\"\"\n"
        ),
        "find": "how='inner'",
        "replace": "how='outer'",
        "snippet": (
            "import pandas as pd\n"
            "left  = pd.DataFrame({'key': [1, 2],    'x': [10, 20]})\n"
            "right = pd.DataFrame({'key': [2, 3],    'y': [200, 300]})\n"
            "result = pd.merge(left, right, on='key')\n"
            "print(len(result), sorted(result['key'].tolist()))\n"
        ),
        "original_output": "1 [2]",
        "correct_output": "3 [1, 2, 3]",
        "distractors": [
            {"text": "1 [2]", "type": "hard_negative", "explanation": "inner join: only key=2 appears in both frames"},
            {"text": "3 [1, 2, 3]", "type": "correct", "explanation": "outer join: union of all keys; key=1 gets NaN for y, key=3 gets NaN for x"},
            {"text": "2 [1, 2]", "type": "plausible_misconception", "explanation": "That would be a left join (all left keys + matching right keys)"},
            {"text": "2 [2, 3]", "type": "plausible_misconception", "explanation": "That would be a right join (all right keys + matching left keys)"},
        ],
        "correct_id": "B",
        "explanation": "outer join takes the union of keys: keys 1, 2, 3 all appear. Key=1 has NaN for y, key=3 has NaN for x.",
        "curriculum_note": "Level 1. The four join types are a frequent confusion point.",
        "is_hard_negative": False,
    },

    {
        "task_id": "concat_ignore_index",
        "family": "index_alignment",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "concat ignore_index=False→True resets index to 0-based integer range",
        "source_file": "pandas/core/reshape/concat.py",
        "source_excerpt": (
            "def concat(objs, axis=0, join='outer', ignore_index=False, ...):\n"
            "    \"\"\"ignore_index : bool, default False\n"
            "        If True, do not use the index values along the concatenation axis.\n"
            "        The resulting axis will be labeled 0, 1, ..., n-1.\n"
            "    \"\"\"\n"
        ),
        "find": "ignore_index=False",
        "replace": "ignore_index=True",
        "snippet": (
            "import pandas as pd\n"
            "df1 = pd.DataFrame({'a': [1, 2]}, index=[10, 20])\n"
            "df2 = pd.DataFrame({'a': [3, 4]}, index=[30, 40])\n"
            "result = pd.concat([df1, df2])\n"
            "print(list(result.index))\n"
        ),
        "original_output": "[10, 20, 30, 40]",
        "correct_output": "[0, 1, 2, 3]",
        "distractors": [
            {"text": "[10, 20, 30, 40]", "type": "hard_negative", "explanation": "Original preserves source indices"},
            {"text": "[0, 1, 2, 3]", "type": "correct", "explanation": "ignore_index=True resets to 0-based range regardless of source indices"},
            {"text": "[0, 10, 20, 30, 40]", "type": "plausible_misconception", "explanation": "Adding a 0 prefix doesn't happen; the entire index is replaced"},
            {"text": "Raises IndexError: duplicate labels", "type": "exception_distractor", "explanation": "concat doesn't raise on index overlap by default"},
        ],
        "correct_id": "B",
        "explanation": "ignore_index=True discards all source index values and replaces with a new RangeIndex(0, n).",
        "curriculum_note": "Level 1. Essential for understanding when to preserve vs reset index.",
        "is_hard_negative": False,
    },

    {
        "task_id": "concat_axis_columns",
        "family": "index_alignment",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "concat axis=0→1 stacks DataFrames as columns instead of rows",
        "source_file": "pandas/core/reshape/concat.py",
        "source_excerpt": (
            "def concat(objs, axis=0, join='outer', ...):\n"
            "    \"\"\"axis : {0/'index', 1/'columns'}, default 0\n"
            "        The axis to concatenate along.\n"
            "        0/index: stack rows (increases row count)\n"
            "        1/columns: stack columns side by side (increases column count)\n"
            "    \"\"\"\n"
        ),
        "find": "axis=0",
        "replace": "axis=1",
        "snippet": (
            "import pandas as pd\n"
            "df1 = pd.DataFrame({'a': [1, 2]})\n"
            "df2 = pd.DataFrame({'b': [3, 4]})\n"
            "result = pd.concat([df1, df2], axis=0)\n"
            "print(result.shape)\n"
        ),
        "original_output": "(4, 2)",
        "correct_output": "(2, 2)",
        "distractors": [
            {"text": "(4, 2)", "type": "hard_negative", "explanation": "axis=0: stacks rows, 4 rows and 2 columns (with NaN fill for missing columns)"},
            {"text": "(2, 2)", "type": "correct", "explanation": "axis=1: places DataFrames side by side, 2 rows and 2 columns"},
            {"text": "(4, 1)", "type": "plausible_misconception", "explanation": "axis=0 would give (4, 1) if both had the same column 'a', but they have different columns"},
            {"text": "(2, 4)", "type": "plausible_misconception", "explanation": "axis=1 doesn't duplicate columns from each frame"},
        ],
        "correct_id": "B",
        "explanation": (
            "axis=0 stacks rows: df1 has 2 rows with col 'a', df2 has 2 rows with col 'b'. "
            "Result is 4 rows × 2 cols (each has NaN for the other's column). "
            "axis=1 stacks columns: 2 rows × 2 cols (a and b side by side)."
        ),
        "curriculum_note": "Level 1. axis parameter is a very common confusion point for concat.",
        "is_hard_negative": False,
    },

    {
        "task_id": "reindex_fill_value",
        "family": "index_alignment",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "reindex fill_value=0 fills missing indices with 0 instead of NaN",
        "source_file": "pandas/core/frame.py",
        "source_excerpt": (
            "def reindex(self, *args, fill_value=np.nan, ...):\n"
            "    \"\"\"fill_value : scalar, default np.nan\n"
            "        Value to use for missing values. Defaults to NaN.\n"
            "    \"\"\"\n"
        ),
        "find": "fill_value=np.nan",
        "replace": "fill_value=0",
        "snippet": (
            "import pandas as pd\n"
            "s = pd.Series([10, 20], index=[0, 1])\n"
            "result = s.reindex([0, 1, 2])\n"
            "print(list(result))\n"
        ),
        "original_output": "[10.0, 20.0, nan]",
        "correct_output": "[10, 20, 0]",
        "distractors": [
            {"text": "[10.0, 20.0, nan]", "type": "hard_negative", "explanation": "Default fill_value=NaN: missing index 2 becomes NaN (and int upcasts to float)"},
            {"text": "[10, 20, 0]", "type": "correct", "explanation": "fill_value=0: missing index 2 gets 0; int dtype preserved since fill value is also int"},
            {"text": "[10, 20, nan]", "type": "plausible_misconception", "explanation": "fill_value=0 replaces NaN with 0, not keeps it as NaN"},
            {"text": "Raises KeyError: 2 not in index", "type": "exception_distractor", "explanation": "reindex doesn't raise for missing labels — it fills them"},
        ],
        "correct_id": "B",
        "explanation": (
            "fill_value=0 replaces the default NaN for missing index positions. "
            "Note: with fill_value=NaN, the int Series upcasts to float64 to hold NaN. "
            "With fill_value=0, the int dtype is preserved."
        ),
        "curriculum_note": "Level 1. Also illustrates the int→float upcast that fill_value=NaN triggers.",
        "is_hard_negative": False,
    },

    {
        "task_id": "merge_duplicate_key_expansion",
        "family": "index_alignment",
        "difficulty": 3,
        "question_type": "behavioral_prediction",
        "description": "merge with duplicate keys in left DataFrame creates a Cartesian product",
        "source_file": "pandas/core/reshape/merge.py",
        "source_excerpt": (
            "# Merging on 'key' with duplicates in the left DataFrame:\n"
            "# Each left row matching a key is paired with each right row matching that key.\n"
            "# If left has 2 rows for key=1 and right has 1 row for key=1,\n"
            "# the result has 2 rows for key=1 (NOT 1 row).\n"
            "#\n"
            "# This is standard SQL inner join behavior (Cartesian product within each key group).\n"
        ),
        "find": "# merge with how='inner' (default)",
        "replace": "# merge with how='inner', validate='1:1'  # would raise MergeError",
        "snippet": (
            "import pandas as pd\n"
            "left  = pd.DataFrame({'key': [1, 1, 2], 'x': [10, 11, 20]})\n"
            "right = pd.DataFrame({'key': [1, 2],    'y': [100, 200]})\n"
            "result = pd.merge(left, right, on='key')\n"
            "print(len(result), list(result['key']))\n"
        ),
        "original_output": "3 [1, 1, 2]",
        "correct_output": "Raises MergeError: Merge keys are not unique in left dataset",
        "distractors": [
            {"text": "3 [1, 1, 2]", "type": "hard_negative", "explanation": "Default merge: duplicate left key=1 pairs with right key=1, giving 2 rows for key=1"},
            {"text": "Raises MergeError: Merge keys are not unique in left dataset", "type": "correct", "explanation": "validate='1:1' explicitly checks uniqueness; duplicate key=1 in left raises MergeError"},
            {"text": "2 [1, 2]", "type": "plausible_misconception", "explanation": "validate doesn't deduplicate — it raises; deduplication would need drop_duplicates()"},
            {"text": "3 [1, 1, 2] (unchanged)", "type": "plausible_misconception", "explanation": "validate='1:1' does not silently pass — it raises when keys are not unique"},
        ],
        "correct_id": "B",
        "explanation": (
            "validate='1:1' checks that merge keys are unique in BOTH frames before merging. "
            "Since key=1 appears twice in the left DataFrame, this raises MergeError. "
            "Without validate, the merge silently creates a Cartesian product for duplicate keys."
        ),
        "curriculum_note": "Level 3: requires understanding merge key uniqueness and validate parameter semantics.",
        "is_hard_negative": False,
    },

    # ------------------------------------------------------------------ copy_semantics
    {
        "task_id": "copy_deep_false",
        "family": "copy_semantics",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "DataFrame.copy(deep=True)→deep=False: shallow copy shares underlying data in pandas <2.0",
        "source_file": "pandas/core/generic.py",
        "source_excerpt": (
            "def copy(self, deep: bool = True) -> NDFrame:\n"
            "    \"\"\"deep : bool, default True\n"
            "        Make a deep copy, including a copy of the data and the indices.\n"
            "        With deep=False, the new object will be created without copying\n"
            "        the calling object's data or index. This is equivalent to\n"
            "        copy.copy(self) in Python.\n"
            "        Note: In pandas >= 2.0 with Copy-on-Write enabled, deep=False is\n"
            "        equivalent to deep=True for mutation purposes.\n"
            "    \"\"\"\n"
        ),
        "find": "deep: bool = True",
        "replace": "deep: bool = False",
        "snippet": (
            "import pandas as pd\n"
            "# pandas < 2.0 behavior (CoW not active)\n"
            "df1 = pd.DataFrame({'a': [1, 2, 3]})\n"
            "df2 = df1.copy()\n"
            "df2.iloc[0, 0] = 99\n"
            "print(df1.iloc[0, 0])\n"
        ),
        "original_output": "1",
        "correct_output": "99",
        "distractors": [
            {"text": "1", "type": "hard_negative", "explanation": "deep=True: df2 is an independent copy; modifying df2 doesn't affect df1"},
            {"text": "99", "type": "correct", "explanation": "deep=False (pandas <2.0): df2 shares underlying data with df1; mutation via df2 affects df1"},
            {"text": "Raises ValueError: cannot modify copy", "type": "exception_distractor", "explanation": "pandas doesn't raise on shallow-copy mutation — the mutation silently propagates"},
            {"text": "1 (CoW prevents mutation)", "type": "plausible_misconception", "explanation": "Copy-on-Write only applies in pandas 2.0+; the question specifies <2.0 behavior"},
        ],
        "correct_id": "B",
        "explanation": (
            "In pandas < 2.0, copy(deep=False) creates a shallow copy that shares the data blocks. "
            "A direct in-place mutation via iloc on df2 modifies the shared block, changing df1 too. "
            "In pandas >= 2.0 with Copy-on-Write, this would NOT affect df1."
        ),
        "curriculum_note": "Level 2. Version-sensitive: CoW in pandas 2.0 changes this behavior.",
        "is_hard_negative": False,
    },

    {
        "task_id": "rename_no_inplace",
        "family": "copy_semantics",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "rename() returns a new DataFrame by default; the original is unchanged",
        "source_file": "pandas/core/generic.py",
        "source_excerpt": (
            "def rename(self, mapper=None, *, index=None, columns=None,\n"
            "           axis=None, copy=True, inplace=False, level=None,\n"
            "           errors='ignore'):\n"
            "    \"\"\"inplace : bool, default False\n"
            "        Whether to return a new {klass}. If True, then the caller is modified.\n"
            "    \"\"\"\n"
        ),
        "find": "# df.rename(columns=...) without inplace=True",
        "replace": "# df.rename(columns=..., inplace=True)",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'old_col': [1, 2, 3]})\n"
            "df.rename(columns={'old_col': 'new_col'})\n"
            "print(list(df.columns))\n"
        ),
        "original_output": "['old_col']",
        "correct_output": "['new_col']",
        "distractors": [
            {"text": "['old_col']", "type": "correct", "explanation": "rename() without inplace=True returns a new DataFrame — df is unchanged"},
            {"text": "['new_col']", "type": "plausible_misconception", "explanation": "The rename result is discarded; df still has the old column name"},
            {"text": "['old_col', 'new_col']", "type": "plausible_misconception", "explanation": "rename replaces the name, doesn't add a second column"},
            {"text": "Raises KeyError: 'old_col' not found", "type": "exception_distractor", "explanation": "errors='ignore' by default; missing keys are silently ignored"},
        ],
        "correct_id": "A",
        "explanation": (
            "rename() has inplace=False by default. The renamed DataFrame is returned but the "
            "return value is discarded here. df still has 'old_col'. "
            "This is a hard negative: the question looks like 'what does rename do?' but the "
            "answer is 'nothing visible, because the result was thrown away'."
        ),
        "curriculum_note": "Level 1 HARD NEGATIVE. Exposes the most common pandas mistake: forgetting to assign rename() result.",
        "is_hard_negative": True,
    },

    # ------------------------------------------------------------------ default_params
    {
        "task_id": "read_csv_header_none",
        "family": "default_params",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "read_csv header=0→None treats first row as data, not column names",
        "source_file": "pandas/io/parsers/readers.py",
        "source_excerpt": (
            "def read_csv(filepath_or_buffer, ..., header='infer', ...):\n"
            "    \"\"\"header : int, list of int, default 'infer'\n"
            "        Row number(s) containing column labels and marking the start of the data.\n"
            "        Default behavior is to infer the header: if no names passed, header=0.\n"
            "        Explicitly pass header=None to indicate there are no column labels.\n"
            "    \"\"\"\n"
        ),
        "find": "header=0",
        "replace": "header=None",
        "snippet": (
            "import pandas as pd\n"
            "from io import StringIO\n"
            "csv_data = 'name,age\\nAlice,30\\nBob,25'\n"
            "df = pd.read_csv(StringIO(csv_data), header=0)\n"
            "print(list(df.columns), len(df))\n"
        ),
        "original_output": "['name', 'age'] 2",
        "correct_output": "[0, 1] 3",
        "distractors": [
            {"text": "['name', 'age'] 2", "type": "hard_negative", "explanation": "header=0: first row is column names; 2 data rows remain"},
            {"text": "[0, 1] 3", "type": "correct", "explanation": "header=None: no header row; columns get integer names (0, 1); all 3 rows are data"},
            {"text": "['0', '1'] 3", "type": "plausible_misconception", "explanation": "pandas uses integer column names (0, 1), not string '0', '1'"},
            {"text": "['name', 'age'] 3", "type": "plausible_misconception", "explanation": "header=None doesn't keep column names from the first row; it treats that row as data"},
        ],
        "correct_id": "B",
        "explanation": (
            "header=None tells pandas there is no header row. Columns get default integer labels (0, 1, ...). "
            "All 3 rows ('name,age', 'Alice,30', 'Bob,25') are treated as data rows."
        ),
        "curriculum_note": "Level 1. Common source of off-by-one row count and unexpected column names.",
        "is_hard_negative": False,
    },

    {
        "task_id": "dropna_axis_default",
        "family": "default_params",
        "difficulty": 1,
        "question_type": "behavioral_prediction",
        "description": "dropna axis=0→1 drops columns with NaN instead of rows",
        "source_file": "pandas/core/frame.py",
        "source_excerpt": (
            "def dropna(self, axis=0, how='any', thresh=None, subset=None, inplace=False):\n"
            "    \"\"\"axis : {0 or 'index', 1 or 'columns'}, default 0\n"
            "        Determine if rows or columns which contain missing values are removed.\n"
            "        0 or 'index': drop rows containing missing values.\n"
            "        1 or 'columns': drop columns containing missing values.\n"
            "    \"\"\"\n"
        ),
        "find": "axis=0",
        "replace": "axis=1",
        "snippet": (
            "import pandas as pd, numpy as np\n"
            "df = pd.DataFrame({'a': [1, 2, np.nan], 'b': [4, 5, 6]})\n"
            "result = df.dropna(axis=0)\n"
            "print(result.shape)\n"
        ),
        "original_output": "(2, 2)",
        "correct_output": "(3, 1)",
        "distractors": [
            {"text": "(2, 2)", "type": "hard_negative", "explanation": "axis=0: drops the row where 'a' is NaN; 2 rows remain, 2 columns"},
            {"text": "(3, 1)", "type": "correct", "explanation": "axis=1: drops column 'a' because it contains NaN; 3 rows remain, 1 column"},
            {"text": "(2, 1)", "type": "plausible_misconception", "explanation": "axis=1 drops the column, not the row — all 3 rows are preserved"},
            {"text": "(3, 0)", "type": "plausible_misconception", "explanation": "Only 'a' has NaN, so only 1 column is dropped; 'b' is retained"},
        ],
        "correct_id": "B",
        "explanation": (
            "axis=1 drops columns that contain NaN values. Column 'a' has one NaN → it is dropped. "
            "Column 'b' has no NaN → it is kept. All 3 rows remain."
        ),
        "curriculum_note": "Level 1. axis=0 vs axis=1 is a perpetual confusion point.",
        "is_hard_negative": False,
    },

    {
        "task_id": "apply_axis_rows",
        "family": "default_params",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "DataFrame.apply axis=0→1 applies function per row instead of per column",
        "source_file": "pandas/core/frame.py",
        "source_excerpt": (
            "def apply(self, func, axis=0, raw=False, result_type=None, args=(), **kwargs):\n"
            "    \"\"\"axis : {0 or 'index', 1 or 'columns'}, default 0\n"
            "        Axis along which the function is applied:\n"
            "        0 or 'index': apply function to each column.\n"
            "        1 or 'columns': apply function to each row.\n"
            "    \"\"\"\n"
        ),
        "find": "axis=0",
        "replace": "axis=1",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'a': [1, 2, 3], 'b': [4, 5, 6]})\n"
            "result = df.apply(lambda x: x.sum(), axis=0)\n"
            "print(list(result.index))\n"
        ),
        "original_output": "['a', 'b']",
        "correct_output": "[0, 1, 2]",
        "distractors": [
            {"text": "['a', 'b']", "type": "hard_negative", "explanation": "axis=0: function applied to each column; result index is column names"},
            {"text": "[0, 1, 2]", "type": "correct", "explanation": "axis=1: function applied to each row; result index is row labels (0, 1, 2)"},
            {"text": "[6, 15]", "type": "plausible_misconception", "explanation": "These are the VALUES (sum of [1,2,3] and [4,5,6]), not the index labels"},
            {"text": "['a', 'b', 0, 1, 2]", "type": "plausible_misconception", "explanation": "axis changes which dimension is iterated — it doesn't concatenate both"},
        ],
        "correct_id": "B",
        "explanation": (
            "axis=0: lambda receives each column as a Series → result is indexed by column names ['a', 'b']. "
            "axis=1: lambda receives each row as a Series → result is indexed by row labels [0, 1, 2]."
        ),
        "curriculum_note": "Level 2. The axis intuition flips: axis=0 iterates over columns, axis=1 over rows.",
        "is_hard_negative": False,
    },

    {
        "task_id": "pivot_table_aggfunc_count",
        "family": "default_params",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "pivot_table aggfunc='mean'→'count' changes what values are computed",
        "source_file": "pandas/core/reshape/pivot.py",
        "source_excerpt": (
            "def pivot_table(data, values=None, index=None, columns=None,\n"
            "                aggfunc='mean', fill_value=None, margins=False, ...):\n"
            "    \"\"\"aggfunc : function, list of functions, dict, default 'mean'\n"
            "        If list of functions passed, the resulting pivot table will have\n"
            "        hierarchical columns whose top-level are the function names.\n"
            "    \"\"\"\n"
        ),
        "find": "aggfunc='mean'",
        "replace": "aggfunc='count'",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'A': ['x', 'x', 'y'], 'B': [1, 3, 5]})\n"
            "result = pd.pivot_table(df, values='B', index='A', aggfunc='mean')\n"
            "print(list(result['B']))\n"
        ),
        "original_output": "[2.0, 5.0]",
        "correct_output": "[2, 1]",
        "distractors": [
            {"text": "[2.0, 5.0]", "type": "hard_negative", "explanation": "mean: x→mean(1,3)=2.0, y→mean(5)=5.0"},
            {"text": "[2, 1]", "type": "correct", "explanation": "count: x has 2 rows, y has 1 row"},
            {"text": "[4, 5]", "type": "plausible_misconception", "explanation": "sum: x→sum(1,3)=4, y→sum(5)=5 — but aggfunc is 'count' not 'sum'"},
            {"text": "[1, 3, 5]", "type": "plausible_misconception", "explanation": "These are the raw values, not the aggregated result"},
        ],
        "correct_id": "B",
        "explanation": "aggfunc='count' counts the number of non-NaN values in each group. Group 'x' has 2 entries, group 'y' has 1 entry.",
        "curriculum_note": "Level 2. Tests understanding of aggregation function semantics.",
        "is_hard_negative": False,
    },

    # ------------------------------------------------------------------ hard_negatives
    {
        "task_id": "noop_series_apply_identity",
        "family": "hard_negatives",
        "difficulty": 3,
        "question_type": "behavioral_prediction",
        "description": "Applying identity function with apply() returns equal values but MAY change dtype",
        "source_file": "pandas/core/series.py",
        "source_excerpt": (
            "# s.apply(lambda x: x) looks like a no-op but can change dtype.\n"
            "# When the lambda returns Python int/float, pandas may infer dtype differently\n"
            "# from the original numpy dtype.\n"
            "#\n"
            "# s.apply(func) where func returns scalars reconstructs the Series from scratch,\n"
            "# using Python type inference rather than preserving the original numpy dtype.\n"
        ),
        "find": "s.apply(lambda x: x)     # identity",
        "replace": "s                        # direct reference",
        "snippet": (
            "import pandas as pd\n"
            "s = pd.Series([1, 2, 3], dtype='int32')\n"
            "result = s.apply(lambda x: x)\n"
            "print(result.dtype)\n"
        ),
        "original_output": "int64",
        "correct_output": "int32",
        "distractors": [
            {"text": "int64", "type": "correct", "explanation": "apply(lambda x: x) reconstructs from Python ints, which default to int64 on most platforms"},
            {"text": "int32", "type": "hard_negative", "explanation": "Looks like a no-op (identity), but apply rebuilds from Python scalars, losing int32"},
            {"text": "object", "type": "plausible_misconception", "explanation": "Python int is not stored as object dtype — pandas infers int64"},
            {"text": "float64", "type": "plausible_misconception", "explanation": "No float conversion happens here; Python int → numpy int64"},
        ],
        "correct_id": "A",
        "explanation": (
            "apply(lambda x: x) is NOT a no-op for dtype. The lambda receives Python scalars and "
            "returns Python ints. When pandas reconstructs the Series from these Python ints, it "
            "uses int64 (the platform default), not the original int32. "
            "This is a hard negative: 'identity function' looks like no-op but isn't."
        ),
        "curriculum_note": "Level 3 HARD NEGATIVE. Tests whether agent assumes apply(identity) preserves all properties.",
        "is_hard_negative": True,
    },

    {
        "task_id": "noop_add_then_subtract",
        "family": "hard_negatives",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "Adding and subtracting the same value returns original values but MAY change dtype",
        "source_file": "pandas/core/ops/array_ops.py",
        "source_excerpt": (
            "# Arithmetic on integer Series with NaN-producing operations:\n"
            "# Adding and subtracting the same float (e.g., + 0.5 - 0.5) looks like no-op.\n"
            "# But intermediate float arithmetic upcasts int64 → float64,\n"
            "# and the final result is float64 even if numerically equal to the original.\n"
        ),
        "find": "# s + 0.5 - 0.5  (hypothetical)",
        "replace": "# s               (no arithmetic)",
        "snippet": (
            "import pandas as pd\n"
            "s = pd.Series([1, 2, 3], dtype='int64')\n"
            "result = s + 0.5 - 0.5\n"
            "print(result.dtype, list(result))\n"
        ),
        "original_output": "float64 [1.0, 2.0, 3.0]",
        "correct_output": "int64 [1, 2, 3]",
        "distractors": [
            {"text": "float64 [1.0, 2.0, 3.0]", "type": "correct", "explanation": "int64 + 0.5 promotes to float64; subtracting 0.5 gives 1.0, 2.0, 3.0 as floats"},
            {"text": "int64 [1, 2, 3]", "type": "hard_negative", "explanation": "Looks like no-op arithmetically, but dtype is permanently promoted to float64"},
            {"text": "int64 [0, 1, 2]", "type": "plausible_misconception", "explanation": "int truncation would give this, but float arithmetic doesn't truncate"},
            {"text": "Raises TypeError: unsupported operand type", "type": "exception_distractor", "explanation": "int64 + float is valid in pandas — no exception"},
        ],
        "correct_id": "A",
        "explanation": (
            "s + 0.5 promotes int64 to float64 (float arithmetic). "
            "Subtracting 0.5 gives numerically correct values, but the dtype remains float64. "
            "The result is [1.0, 2.0, 3.0] with dtype=float64, not int64."
        ),
        "curriculum_note": "Level 2 HARD NEGATIVE. dtype promotion is permanent once float arithmetic is applied.",
        "is_hard_negative": True,
    },

    {
        "task_id": "noop_set_index_reset_index",
        "family": "hard_negatives",
        "difficulty": 2,
        "question_type": "behavioral_prediction",
        "description": "set_index then reset_index(drop=False) looks like no-op but adds a column",
        "source_file": "pandas/core/frame.py",
        "source_excerpt": (
            "# df.set_index('col') moves 'col' from columns to index.\n"
            "# df.reset_index(drop=False) moves the index back to columns.\n"
            "# If the original index was RangeIndex, reset_index adds an 'index' column.\n"
            "#\n"
            "# set_index('col').reset_index(drop=False) is NOT a no-op:\n"
            "#   - Original: RangeIndex + columns [col, val]\n"
            "#   - After: RangeIndex + columns [col, val, 'index'... wait, no]\n"
            "#   Actually: set_index('col') → index=col, columns=[val]\n"
            "#             reset_index(drop=False) → index=RangeIndex, columns=[col, val]\n"
            "#   So this IS a no-op in terms of column content, but index is reset.\n"
        ),
        "find": "# df.set_index('key').reset_index(drop=False)",
        "replace": "# df  (direct reference, no transforms)",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'key': ['a', 'b'], 'val': [1, 2]}, index=[10, 20])\n"
            "result = df.set_index('key').reset_index(drop=False)\n"
            "print(list(result.columns), list(result.index))\n"
        ),
        "original_output": "['key', 'val'] [0, 1]",
        "correct_output": "['key', 'val'] [10, 20]",
        "distractors": [
            {"text": "['key', 'val'] [0, 1]", "type": "correct", "explanation": "set_index loses original index (10,20); reset_index creates new RangeIndex (0,1)"},
            {"text": "['key', 'val'] [10, 20]", "type": "hard_negative", "explanation": "Looks like round-trip no-op, but set_index discards original index 10,20"},
            {"text": "['index', 'key', 'val'] [0, 1]", "type": "plausible_misconception", "explanation": "set_index('key') moves key to index; reset_index moves it back — no 'index' column added since key was named"},
            {"text": "['key', 'val'] [10, 20, 10, 20]", "type": "plausible_misconception", "explanation": "set_index doesn't duplicate the index"},
        ],
        "correct_id": "A",
        "explanation": (
            "set_index('key') replaces the original index [10, 20] with 'key' as the index. "
            "The original RangeIndex [10, 20] is discarded. "
            "reset_index(drop=False) creates a new RangeIndex [0, 1], not [10, 20]. "
            "This looks like a round-trip but the original index is lost."
        ),
        "curriculum_note": "Level 2 HARD NEGATIVE. set_index destroys the original index — round-trip is not identity.",
        "is_hard_negative": True,
    },

    # ------------------------------------------------------------------ cross_layer (difficulty 4)
    {
        "task_id": "groupby_agg_sort_affects_cumsum",
        "family": "sort_order",
        "difficulty": 4,
        "question_type": "counterfactual_cascade",
        "description": "groupby sort=False affects cumsum order within groups when groups appear interleaved",
        "source_file": "pandas/core/groupby/groupby.py",
        "source_excerpt": (
            "# With sort=True, groupby collects all rows for each group (sorted by key),\n"
            "# then applies the operation. Groups are contiguous in the output.\n"
            "#\n"
            "# With sort=False, groups are processed in first-occurrence order.\n"
            "# For transform operations like cumsum, the row ORDER in the output\n"
            "# matches the original DataFrame row order, not sorted group order.\n"
        ),
        "find": "sort=True",
        "replace": "sort=False",
        "snippet": (
            "import pandas as pd\n"
            "df = pd.DataFrame({'g': ['b', 'a', 'b', 'a'], 'v': [1, 10, 2, 20]})\n"
            "result = df.groupby('g', sort=True)['v'].cumsum()\n"
            "print(list(result))\n"
        ),
        "original_output": "[1, 10, 3, 30]",
        "correct_output": "[1, 10, 3, 30]",
        "distractors": [
            {"text": "[1, 10, 3, 30]", "type": "correct", "explanation": "cumsum is a transform: result aligns with original row order regardless of sort. Both sort=True and sort=False give same output."},
            {"text": "[10, 1, 30, 3]", "type": "plausible_misconception", "explanation": "sort=True doesn't reorder rows in transform output — result always aligns with input rows"},
            {"text": "[1, 3, 10, 30]", "type": "plausible_misconception", "explanation": "This would be cumsum if rows were sorted by group ('b','b','a','a') — but that's not what transform does"},
            {"text": "[1, 11, 3, 31]", "type": "plausible_misconception", "explanation": "cumsum is within-group, not global. Groups 'a' and 'b' are independent."},
        ],
        "correct_id": "A",
        "explanation": (
            "This is a hard negative (Level 4). For TRANSFORM operations (like cumsum), "
            "sort= does NOT affect the output. Transform always returns a Series aligned to "
            "the original row order. sort= only affects AGGREGATION operations like sum() or mean(). "
            "Both sort=True and sort=False give identical cumsum output."
        ),
        "curriculum_note": "Level 4 HARD NEGATIVE. sort= affects agg output order but NOT transform output. Tests whether agent over-generalizes sort= effect.",
        "is_hard_negative": True,
    },

    {
        "task_id": "merge_on_index_vs_column",
        "family": "index_alignment",
        "difficulty": 3,
        "question_type": "causal_attribution",
        "description": "Merging on index (left_index=True) vs column ('key') gives different row counts when index has duplicates",
        "source_file": "pandas/core/reshape/merge.py",
        "source_excerpt": (
            "def merge(left, right, how='inner', on=None,\n"
            "          left_on=None, right_on=None,\n"
            "          left_index=False, right_index=False, ...):\n"
            "    \"\"\"left_index : bool, default False\n"
            "        Use the index from the left DataFrame as the join key(s).\n"
            "        If it is a MultiIndex, the number of keys in the other DataFrame\n"
            "        (either the index or a number of columns) must match the number of levels.\n"
            "    \"\"\"\n"
        ),
        "find": "on='key'",
        "replace": "left_index=True, right_on='key'",
        "snippet": (
            "import pandas as pd\n"
            "left  = pd.DataFrame({'val': [10, 20]}, index=[1, 2])\n"
            "right = pd.DataFrame({'key': [1, 2, 1], 'y': [100, 200, 300]})\n"
            "# Original: left has column 'key'=[1,2]; merge on='key'\n"
            "# Change: use left index as key instead\n"
            "result = pd.merge(left, right, left_index=True, right_on='key')\n"
            "print(len(result))\n"
        ),
        "original_output": "2",
        "correct_output": "3",
        "distractors": [
            {"text": "2", "type": "hard_negative", "explanation": "If left had a 'key' column [1,2] with no duplicates, merge on='key' gives 2 rows"},
            {"text": "3", "type": "correct", "explanation": "left index [1,2] merges against right 'key' [1,2,1]; index=1 matches right rows 0 and 2, giving 3 rows"},
            {"text": "4", "type": "plausible_misconception", "explanation": "left index 1 matches right key 1 twice (rows 0, 2); left index 2 matches once (row 1). Total = 3."},
            {"text": "Raises KeyError: 'key' not in left", "type": "exception_distractor", "explanation": "left_index=True uses the left index, not a column — KeyError doesn't apply"},
        ],
        "correct_id": "B",
        "explanation": (
            "left_index=True uses left's index [1, 2] as the join key. "
            "Right has 'key' values [1, 2, 1]. "
            "Left index=1 matches right rows where key=1 (rows 0 and 2): 2 matches. "
            "Left index=2 matches right row where key=2 (row 1): 1 match. "
            "Total: 3 rows."
        ),
        "curriculum_note": "Level 3: requires tracing index vs column semantics and understanding duplicate key expansion.",
        "is_hard_negative": False,
    },

]
