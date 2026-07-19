use pine_sema::analyze_source;
use pine_syntax::SourceFile;

use super::*;

#[test]
fn runs_float_array_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array ops")
values = array.new_float(2, close)
array.push(values, high)
array.set(values, 0, low)
first = array.get(values, 0)
last = array.pop(values)
empty = array.new_float()
plot(first + last + array.size(values))
plot(na(array.pop(empty)) and array.size(empty) == 0 ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[4.0, 6.0, 8.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_float_array_method_calls() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array methods")
values = array.new_float(2, close)
values.push(high)
values.set(0, low)
first = values.get(0)
last = values.pop()
empty = array.new_float()
plot(first + last + values.size())
plot(na(empty.pop()) and empty.size() == 0 ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[4.0, 6.0, 8.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_int_array_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("int array ops")
values = array.new_int(2, bar_index)
array.push(values, 10)
array.set(values, 0, 3)
first = array.get(values, 0)
last = array.pop(values)
plot(first + last + array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[15.0, 15.0, 15.0]);
}

#[test]
fn runs_array_get_with_computed_integer_index() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("computed array index")
values = array.from(10, 20, 30)
k = 2
plot(array.get(values, k - 1))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[20.0, 20.0, 20.0]);
}

#[test]
fn runs_int_array_method_calls() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("int array methods")
values = array.new_int(2, bar_index)
values.push(10)
values.set(0, 3)
first = values.get(0)
last = values.pop()
plot(first + last + values.size())
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[15.0, 15.0, 15.0]);
}

#[test]
fn runs_array_mutation_and_size_with_computed_integer_operands() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("computed array operands")
n = 1
values = array.new_float(n + 1)
array.set(values, n - 1, close)
array.set(values, n, close + 10)
plot(array.get(values, n - 1))
plot(array.get(values, n))
plot(array.size(values))
ints = array.new_int(n + 2, n)
flags = array.new_bool(n + 1, bar_index >= 0)
words = array.new_string(n + 1, "seed")
colors = array.new_color(n + 1, color.red)
plot(array.size(ints) + array.get(ints, 0))
plot(array.size(flags) + (array.get(flags, n) ? 1 : 0))
plot(array.size(words) + (array.get(words, n) == "seed" ? 1 : 0))
plot(array.size(colors) + (array.get(colors, n) == color.red ? 1 : 0))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
    assert_values_close(&result.plots[1].values, &[11.0, 12.0, 13.0]);
    assert_values_close(&result.plots[2].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[3].values, &[4.0, 4.0, 4.0]);
    assert_values_close(&result.plots[4].values, &[3.0, 3.0, 3.0]);
    assert_values_close(&result.plots[5].values, &[3.0, 3.0, 3.0]);
    assert_values_close(&result.plots[6].values, &[3.0, 3.0, 3.0]);
}

#[test]
fn runs_bool_array_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bool array ops")
values = array.new_bool(2, close > open)
array.push(values, true)
array.set(values, 0, false)
first = array.get(values, 0)
last = array.pop(values)
plot((first or last) ? array.size(values) : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0, 2.0]);
}

#[test]
fn runs_bool_array_method_calls() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bool array methods")
values = array.new_bool(2, close > open)
values.push(true)
values.set(0, false)
first = values.get(0)
last = values.pop()
plot((first or last) ? values.size() : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0, 2.0]);
}

#[test]
fn runs_string_array_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("string array ops")
values = array.new_string(2, "seed")
array.push(values, "tail")
array.set(values, 0, "head")
first = array.get(values, 0)
last = array.pop(values)
text = str.tostring(values)
plot(first == "head" and last == "tail" ? array.size(values) : 0)
plot(text == "[head, seed]" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_string_array_method_calls() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("string array methods")
values = array.new_string(2, "seed")
values.push("tail")
values.set(0, "head")
first = values.get(0)
last = values.pop()
text = str.format("Values {0}", values)
plot(first == "head" and last == "tail" ? values.size() : 0)
plot(text == "Values [head, seed]" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_color_array_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("color array ops")
values = array.new_color(2, color.red)
array.push(values, color.green)
array.set(values, 0, color.blue)
first = array.get(values, 0)
last = array.pop(values)
plot(first == color.blue and last == color.green ? array.size(values) : 0)
plot(color.b(first) + color.g(last))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[1].values, &[418.0, 418.0, 418.0]);
}

#[test]
fn runs_color_array_method_calls() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("color array methods")
values = array.new_color(2, color.red)
values.push(color.green)
values.set(0, color.blue)
first = values.get(0)
last = values.pop()
plot(first == color.blue and last == color.green ? values.size() : 0)
plot(color.b(first) + color.g(last))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[1].values, &[418.0, 418.0, 418.0]);
}

#[test]
fn runs_array_clear_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array clear")
floats = array.from(close, high, na)
array.clear(floats)
array.clear(floats)
array.push(floats, low)
plot(array.size(floats))
plot(array.get(floats, 0))

ints = array.from(bar_index, 10)
ints.clear()
ints.push(7)
plot(ints.size())
plot(ints.get(0))

flags = array.from(true, false)
array.clear(flags)
flags.push(bar_index == 0)
plot(flags.size())
plot(flags.get(0) ? 1 : 0)

words = array.from("a", "b")
words.clear()
words.push("z")
plot(words.size())
plot(words.get(0) == "z" ? 1 : 0)

colors = array.from(color.red, color.green)
array.clear(colors)
colors.push(color.blue)
plot(colors.size())
plot(colors.get(0) == color.blue ? 1 : 0)

empty = array.new_float()
empty.clear()
plot(empty.size())
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 11);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 2.0, 3.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[7.0, 7.0, 7.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[1.0, 0.0, 0.0]);
    assert_values_close(&result.plots[6].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[7].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[8].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[9].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[10].values, &[0.0, 0.0, 0.0]);
}

#[test]
fn runs_array_helper_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array helpers")
values = array.new_int()
array.unshift(values, 2)
array.unshift(values, 1)
first = array.first(values)
last = array.last(values)
shifted = array.shift(values)
empty = array.new_string()
plot(first + last + shifted + array.size(values))
plot(array.first(values) == 2 and array.size(values) == 1 ? 1 : 0)
plot(na(array.first(empty)) and na(array.last(empty)) and na(array.shift(empty)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[5.0, 5.0, 5.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_array_helper_method_calls() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array helper methods")
values = array.new_string()
values.unshift("tail")
values.unshift("head")
first = values.first()
last = values.last()
shifted = values.shift()
colors = array.new_color()
colors.unshift(color.green)
colors.unshift(color.red)
color_first = colors.first()
color_last = colors.last()
color_shifted = colors.shift()
plot(first == "head" and last == "tail" and shifted == "head" ? values.size() : 0)
plot(color_first == color.red and color_last == color.green and color_shifted == color.red ? colors.size() : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_array_insert_remove_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array insert remove")
ints = array.new_int()
ints.push(1)
ints.push(3)
array.insert(ints, 1, 2)
removed = ints.remove(0)
plot(removed)
plot(ints.get(0) * 10 + ints.get(1))

words = array.new_string()
words.push("a")
words.push("c")
words.insert(1, "b")
word_removed = array.remove(words, 2)
plot(word_removed == "c" and words.join("|") == "a|b" ? 1 : 0)

colors = array.new_color()
colors.push(color.red)
colors.insert(1, color.green)
color_removed = colors.remove(0)
plot(color_removed == color.red and colors.get(0) == color.green ? 1 : 0)

flags = array.new_bool()
flags.insert(0, true)
plot(flags.remove(0) ? flags.size() : 99)

negative = array.from(10, 20, 30)
plot(negative.get(-1) + negative.get(-3))
negative.set(-2, 99)
plot(negative.get(1))
negative.insert(-1, 25)
plot(negative.get(2) * 100 + negative.get(-1))
negative_head = negative.remove(-4)
negative_tail = negative.remove(-1)
plot(negative_head + negative_tail + negative.size())
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 9);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[23.0, 23.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[4].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[5].values, &[40.0, 40.0]);
    assert_values_close(&result.plots[6].values, &[99.0, 99.0]);
    assert_values_close(&result.plots[7].values, &[2530.0, 2530.0]);
    assert_values_close(&result.plots[8].values, &[42.0, 42.0]);
}

#[test]
fn runs_array_fill_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array fill")
ints = array.new_int(4, 1)
array.fill(ints, 9, 1, 3)
plot(ints.get(0) * 1000 + ints.get(1) * 100 + ints.get(2) * 10 + ints.get(3))
ints.fill(2)
plot(ints.get(0) + ints.get(3))

floats = array.new_float(3, close)
floats.fill(high, 0, 2)
plot(floats.get(0) + floats.get(1) + floats.get(2))

words = array.new_string(3, "a")
words.fill("b", 1, 3)
plot(words.join("|") == "a|b|b" ? 1 : 0)

colors = array.new_color(2, color.red)
colors.fill(color.green)
plot(colors.get(0) == color.green and colors.get(1) == color.green ? 1 : 0)

flags = array.new_bool(2, false)
array.fill(flags, true, 0, 1)
plot(flags.get(0) and not flags.get(1) ? 1 : 0)

array.fill(flags, false, -1, 1)
array.fill(flags, false, 0, 3)
plot(flags.get(0) and not flags.get(1) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 4.0, 0.0, 2.0), bar_ohlc(2.0, 6.0, 1.0, 3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 7);
    assert_values_close(&result.plots[0].values, &[1991.0, 1991.0]);
    assert_values_close(&result.plots[1].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[2].values, &[10.0, 15.0]);
    assert_values_close(&result.plots[3].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[6].values, &[1.0, 1.0]);
}

#[test]
fn runs_array_from_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array from")
type Point
    float x

ints = array.from(1, 2, 3)
plot(ints.size())
plot(ints.sum())
ints.push(4)
plot(ints.last())

floats = array.from(1, close, na)
plot(floats.get(0) + floats.get(1))
plot(na(floats.get(2)) ? 1 : 0)

flags = array.from(true, false)
plot(flags.get(0) and not flags.get(1) ? 1 : 0)

words = array.from("a", "b")
plot(words.join("|") == "a|b" ? 1 : 0)

colors = array.from(color.red, color.green)
plot(colors.get(0) == color.red and colors.get(1) == color.green ? 1 : 0)

points = array.from(Point.new(close), Point.new(open))
array.set(points, 0, Point.new(high))
points.set(1, Point.new(low))
array.push(points, Point.new(close + open))
points.push(Point.new(high + low))
first_point = array.get(points, 0)
second_point = points.get(1)
third_point = array.get(points, 2)
fourth_point = points.get(3)
first_reader_point = array.first(points)
method_first_reader_point = points.first()
last_reader_point = array.last(points)
method_last_reader_point = points.last()
popped_point = array.pop(points)
method_popped_point = points.pop()
shifted_point = array.shift(points)
method_shifted_point = points.shift()
cleared_points = array.from(Point.new(close), Point.new(open))
array.clear(cleared_points)
cleared_points_empty_size = array.size(cleared_points)
array.push(cleared_points, Point.new(high))
cleared_reader_point = array.get(cleared_points, 0)
method_cleared_points = array.from(Point.new(close), Point.new(open))
method_cleared_points.clear()
method_cleared_points_empty_size = method_cleared_points.size()
method_cleared_points.push(Point.new(low))
method_cleared_reader_point = method_cleared_points.get(0)
copy_source_points = array.from(Point.new(close), Point.new(open))
copied_points = array.copy(copy_source_points)
method_copied_points = copy_source_points.copy()
array.push(copied_points, Point.new(high))
method_copied_points.push(Point.new(low))
copy_reader_point = array.get(copied_points, 0)
copy_added_point = copied_points.get(2)
method_copy_added_point = method_copied_points.get(2)
reverse_points = array.from(Point.new(close), Point.new(open))
array.reverse(reverse_points)
reverse_first_point = array.get(reverse_points, 0)
reverse_second_point = reverse_points.get(1)
method_reverse_points = array.from(Point.new(high), Point.new(low))
method_reverse_points.reverse()
method_reverse_first_point = method_reverse_points.get(0)
method_reverse_second_point = method_reverse_points.get(1)
concat_left_points = array.from(Point.new(close))
concat_right_points = array.from(Point.new(open), Point.new(high))
concat_returned_points = array.concat(concat_left_points, concat_right_points)
concat_added_point = concat_returned_points.get(2)
method_concat_left_points = array.from(Point.new(low))
method_concat_right_points = array.from(Point.new(high), Point.new(open))
method_concat_returned_points = method_concat_left_points.concat(method_concat_right_points)
method_concat_added_point = method_concat_returned_points.get(2)
slice_source_points = array.from(Point.new(close), Point.new(open), Point.new(high))
slice_window_points = array.slice(slice_source_points, 1, 3)
slice_first_point = slice_window_points.get(0)
array.set(slice_window_points, 0, Point.new(low))
slice_parent_point = slice_source_points.get(1)
method_slice_source_points = array.from(Point.new(close), Point.new(open), Point.new(high))
method_slice_window_points = method_slice_source_points.slice(0, 2)
method_slice_source_points.set(1, Point.new(low))
method_slice_second_point = method_slice_window_points.get(1)
insert_points = array.from(Point.new(close), Point.new(high))
array.insert(insert_points, 1, Point.new(open))
insert_inserted_point = insert_points.get(1)
insert_tail_point = insert_points.get(2)
method_insert_points = array.from(Point.new(low), Point.new(close))
method_insert_points.insert(1, Point.new(high))
method_insert_inserted_point = method_insert_points.get(1)
method_insert_tail_point = method_insert_points.get(2)
remove_points = array.from(Point.new(close), Point.new(open), Point.new(high))
removed_point = array.remove(remove_points, 1)
remove_after_point = remove_points.get(1)
method_remove_points = array.from(Point.new(low), Point.new(close), Point.new(open))
method_removed_point = method_remove_points.remove(0)
method_remove_after_point = method_remove_points.get(0)
unshift_points = array.from(Point.new(close), Point.new(high))
array.unshift(unshift_points, Point.new(open))
unshift_first_point = unshift_points.get(0)
unshift_second_point = unshift_points.get(1)
method_unshift_points = array.from(Point.new(low), Point.new(close))
method_unshift_points.unshift(Point.new(high))
method_unshift_first_point = method_unshift_points.get(0)
method_unshift_second_point = method_unshift_points.get(1)
plot(array.size(points))
plot(points.size())
plot(first_point.x + second_point.x)
plot(third_point.x + fourth_point.x)
plot(first_reader_point.x)
plot(method_first_reader_point.x)
plot(last_reader_point.x)
plot(method_last_reader_point.x)
plot(popped_point.x)
plot(method_popped_point.x)
plot(shifted_point.x)
plot(method_shifted_point.x)
plot(cleared_points_empty_size)
plot(array.size(cleared_points))
plot(cleared_reader_point.x)
plot(method_cleared_points_empty_size)
plot(method_cleared_points.size())
plot(method_cleared_reader_point.x)
plot(array.size(copy_source_points))
plot(array.size(copied_points))
plot(method_copied_points.size())
plot(copy_reader_point.x)
plot(copy_added_point.x)
plot(method_copy_added_point.x)
plot(reverse_first_point.x)
plot(reverse_second_point.x)
plot(method_reverse_first_point.x)
plot(method_reverse_second_point.x)
plot(array.size(concat_returned_points))
plot(concat_added_point.x)
plot(array.size(concat_right_points))
plot(method_concat_returned_points.size())
plot(method_concat_added_point.x)
plot(method_concat_right_points.size())
plot(slice_window_points.size())
plot(slice_first_point.x)
plot(slice_parent_point.x)
plot(method_slice_window_points.size())
plot(method_slice_second_point.x)
plot(method_slice_source_points.size())
plot(insert_points.size())
plot(insert_inserted_point.x)
plot(insert_tail_point.x)
plot(method_insert_points.size())
plot(method_insert_inserted_point.x)
plot(method_insert_tail_point.x)
plot(remove_points.size())
plot(removed_point.x)
plot(remove_after_point.x)
plot(method_remove_points.size())
plot(method_removed_point.x)
plot(method_remove_after_point.x)
plot(unshift_points.size())
plot(unshift_first_point.x)
plot(unshift_second_point.x)
plot(method_unshift_points.size())
plot(method_unshift_first_point.x)
plot(method_unshift_second_point.x)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 4.0, 0.0, 2.0), bar_ohlc(2.0, 6.0, 1.0, 3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 66);
    assert_values_close(&result.plots[0].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[1].values, &[6.0, 6.0]);
    assert_values_close(&result.plots[2].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[3].values, &[3.0, 4.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[6].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[7].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[8].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[9].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[10].values, &[4.0, 7.0]);
    assert_values_close(&result.plots[11].values, &[7.0, 12.0]);
    assert_values_close(&result.plots[12].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[13].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[14].values, &[4.0, 7.0]);
    assert_values_close(&result.plots[15].values, &[4.0, 7.0]);
    assert_values_close(&result.plots[16].values, &[4.0, 7.0]);
    assert_values_close(&result.plots[17].values, &[3.0, 5.0]);
    assert_values_close(&result.plots[18].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[19].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[20].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[21].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[22].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[23].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[24].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[25].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[26].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[27].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[28].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[29].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[30].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[31].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[32].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[33].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[34].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[35].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[36].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[37].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[38].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[39].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[40].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[41].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[42].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[43].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[44].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[45].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[46].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[47].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[48].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[49].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[50].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[51].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[52].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[53].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[54].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[55].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[56].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[57].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[58].values, &[0.0, 1.0]);
    assert_values_close(&result.plots[59].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[60].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[61].values, &[1.0, 2.0]);
    assert_values_close(&result.plots[62].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[63].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[64].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[65].values, &[0.0, 1.0]);
}

#[test]
fn runs_array_reference_and_copy_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array references")
first_int(values) => values.get(0)
int_size(values) => array.size(values)

source = array.new_int()
alias = source
copy = array.copy(source)
method_copy = source.copy()
array.push(alias, 1)
array.push(copy, 2)
method_copy.push(3)
plot(array.size(source))
plot(array.get(source, 0))
plot(array.size(copy))
plot(array.get(copy, 0))
plot(method_copy.size())
plot(method_copy.get(0))
plot(first_int(source) + int_size(source))
plot(first_int(copy) + int_size(copy))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 8);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[4].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[5].values, &[3.0, 3.0, 3.0]);
    assert_values_close(&result.plots[6].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[7].values, &[3.0, 3.0, 3.0]);
}

#[test]
fn runs_varip_array_with_var_like_historical_state() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("varip arrays")
varip values = array.new_int()
values.push(1)

varip alias = values
alias.push(20)
plot(values.size())
plot(alias.size())

varip copy = array.copy(values)
copy.push(10)
plot(copy.size())
plot(values.size())

branch_out = close - close
if close >= 3
    varip branch = array.new_int()
    branch.push(1)
    branch_out := branch.size()
plot(branch_out)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0), bar(4.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 5);
    assert_values_close(&result.plots[0].values, &[2.0, 4.0, 6.0, 8.0]);
    assert_values_close(&result.plots[1].values, &[2.0, 4.0, 6.0, 8.0]);
    assert_values_close(&result.plots[2].values, &[3.0, 4.0, 5.0, 6.0]);
    assert_values_close(&result.plots[3].values, &[2.0, 4.0, 6.0, 8.0]);
    assert_values_close(&result.plots[4].values, &[0.0, 0.0, 1.0, 2.0]);
}

#[test]
fn runs_array_search_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array search")
numbers = array.new_int()
array.push(numbers, 2)
array.push(numbers, 3)
array.push(numbers, 2)
plot(array.includes(numbers, 2) ? 1 : 0)
plot(array.indexof(numbers, 2))
plot(array.lastindexof(numbers, 2))
plot(numbers.indexof(9))
array.sort(numbers)
plot(array.binary_search(numbers, 2))
plot(numbers.binary_search(9))
plot(array.binary_search_leftmost(numbers, 4))
plot(array.binary_search_rightmost(numbers, 4))
plot(numbers.binary_search_leftmost(2))
plot(numbers.binary_search_rightmost(2))
plot(array.binary_search_leftmost(numbers, 1) == 0 and array.binary_search_rightmost(numbers, 1) == 0 and array.binary_search_leftmost(numbers, 9) == 2 and array.binary_search_rightmost(numbers, 9) == 2 ? 1 : 0)
empty_numbers = array.new_int()
plot(empty_numbers.binary_search(1))

truth_flags = array.from(true, true)
plot(array.every(truth_flags) and truth_flags.some() ? 1 : 0)
truth_flags.push(false)
plot(array.every(truth_flags) ? 99 : (array.some(truth_flags) ? 1 : 0))
truth_numbers = array.from(1, -2, 3)
plot(truth_numbers.every() and array.some(truth_numbers) ? 1 : 0)
truth_numbers.push(0)
plot(array.every(truth_numbers) ? 99 : 1)
truth_floats = array.new_float()
truth_floats.push(na)
truth_floats.push(0)
truth_floats.push(close)
plot(array.every(truth_floats) ? 99 : (truth_floats.some() ? 1 : 0))
empty_truth = array.new_bool()
plot(array.every(empty_truth) and not empty_truth.some() ? 1 : 0)
na_truth = array.new_int(2)
plot(array.every(na_truth) ? 99 : (array.some(na_truth) ? 98 : 1))

words = array.new_string()
words.push("a")
words.push("b")
words.push("a")
plot(words.includes("b") ? words.lastindexof("a") : 0)
plot(words.indexof("z") == -1 and words.lastindexof("z") == -1 ? 1 : 0)

colors = array.new_color()
colors.push(color.red)
colors.push(color.green)
plot(colors.includes(color.green) ? colors.indexof(color.green) : 0)

bool_search = array.from(true, true)
plot(bool_search.indexof(true) == 0 and bool_search.lastindexof(true) == 1 and bool_search.indexof(false) == -1 and bool_search.lastindexof(false) == -1 ? 1 : 0)
plot(not words.includes("z") and not bool_search.includes(false) ? 1 : 0)
empty_truth_ints = array.new_int()
empty_truth_floats = array.new_float()
plot(empty_truth_ints.every() and not empty_truth_ints.some() and array.every(empty_truth_floats) and not array.some(empty_truth_floats) ? 1 : 0)
empty_float_search = array.new_float()
plot(empty_float_search.binary_search(close) == -1 and empty_float_search.binary_search_leftmost(close) == -1 and empty_float_search.binary_search_rightmost(close) == -1 ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 26);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[2].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[3].values, &[-1.0, -1.0, -1.0]);
    assert_values_close(&result.plots[4].values, &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[5].values, &[-1.0, -1.0, -1.0]);
    assert_values_close(&result.plots[6].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[7].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[8].values, &[0.0, 0.0, 0.0]);
    assert_values_close(&result.plots[9].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[-1.0, -1.0, -1.0]);
    assert_values_close(&result.plots[12].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[13].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[14].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[15].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[16].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[17].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[18].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[19].values, &[2.0, 2.0, 2.0]);
    assert_values_close(&result.plots[20].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[21].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[22].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[23].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[24].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[25].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn runs_numeric_array_statistics() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array statistics")
ints = array.new_int()
array.push(ints, 2)
array.push(ints, 5)
array.push(ints, 1)
plot(array.min(ints))
plot(array.max(ints))
plot(array.sum(ints))
plot(array.avg(ints))
plot(array.range(ints))
plot(array.median(ints))
plot(array.percentile_nearest_rank(ints, 50))
plot(ints.percentile_linear_interpolation(75))
plot(array.percentrank(ints, 1))
plot(array.variance(ints, false))
mode_ints = array.from(1, 3, 3, 2, 2)
plot(mode_ints.mode())

floats = array.new_float()
floats.push(close)
floats.push(high)
floats.push(na)
plot(floats.min())
plot(floats.max())
plot(floats.sum())
plot(floats.avg())
plot(floats.range())
plot(floats.median())
plot(floats.percentile_nearest_rank(50))
plot(array.percentile_linear_interpolation(floats, 50))
plot(floats.percentrank(1))
plot(array.variance(floats))
plot(floats.stdev(false))

signs = array.from(-2, 0, 3)
absolutes = signs.abs()
plot(absolutes.get(0) + absolutes.get(1) + absolutes.get(2))
plot(signs.get(0))
float_signs = array.new_float()
float_signs.push(-close)
float_signs.push(na)
float_abs = array.abs(float_signs)
plot(float_abs.get(0))
plot(na(float_abs.get(1)) ? 1 : 0)

standard_values = array.from(2, 4, 4, 4, 5, 5, 7, 9)
standardized = standard_values.standardize()
plot(standardized.get(0))
plot(standardized.get(7))
plot(standard_values.get(0))
standard_with_na = array.from(close, na, high)
standardized_with_na = array.standardize(standard_with_na)
plot(standardized_with_na.size())
plot(na(standardized_with_na.get(1)) ? 1 : 0)

covariance_x = array.from(1, 2, 3)
covariance_y = array.from(1, 5, 7)
plot(array.covariance(covariance_x, covariance_y))
plot(covariance_x.covariance(covariance_y, false))
covariance_with_na_x = array.from(close, na, high)
covariance_with_na_y = array.from(open, close, na)
plot(array.covariance(covariance_with_na_x, covariance_with_na_y))
plot(na(covariance_with_na_x.covariance(covariance_with_na_y, false)) ? 1 : 0)
mismatched_covariance = array.from(1, 2)
plot(na(array.covariance(covariance_x, mismatched_covariance)) ? 1 : 0)

empty = array.new_float()
only_na = array.new_int(2)
empty_standardized = array.standardize(empty)
only_na_standardized = only_na.standardize()
plot(na(array.min(empty)) and na(array.max(only_na)) and na(array.sum(empty)) and na(array.avg(only_na)) and na(array.range(empty)) and na(array.mode(ints)) and na(array.percentile_nearest_rank(empty, 50)) and na(array.percentile_linear_interpolation(ints, 150)) and na(array.percentrank(empty, 0)) and empty_standardized.size() == 0 and only_na_standardized.size() == 0 and na(array.covariance(empty, empty)) and na(array.variance(empty)) and na(only_na.stdev()) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 4.0, 0.0, 2.0), bar_ohlc(2.0, 6.0, 1.0, 3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 37);
    assert_values_close(&result.plots[0].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[1].values, &[5.0, 5.0]);
    assert_values_close(&result.plots[2].values, &[8.0, 8.0]);
    assert_values_close(&result.plots[3].values, &[8.0 / 3.0, 8.0 / 3.0]);
    assert_values_close(&result.plots[4].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[5].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[6].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[7].values, &[3.5, 3.5]);
    assert_values_close(&result.plots[8].values, &[100.0, 100.0]);
    assert_values_close(&result.plots[9].values, &[13.0 / 3.0, 13.0 / 3.0]);
    assert_values_close(&result.plots[10].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[11].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[12].values, &[4.0, 6.0]);
    assert_values_close(&result.plots[13].values, &[6.0, 9.0]);
    assert_values_close(&result.plots[14].values, &[3.0, 4.5]);
    assert_values_close(&result.plots[15].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[16].values, &[3.0, 4.5]);
    assert_values_close(&result.plots[17].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[18].values, &[3.0, 4.5]);
    assert_values_close(&result.plots[19].values, &[100.0, 100.0]);
    assert_values_close(&result.plots[20].values, &[1.0, 2.25]);
    assert_values_close(&result.plots[21].values, &[2.0_f64.sqrt(), 4.5_f64.sqrt()]);
    assert_values_close(&result.plots[22].values, &[5.0, 5.0]);
    assert_values_close(&result.plots[23].values, &[-2.0, -2.0]);
    assert_values_close(&result.plots[24].values, &[2.0, 3.0]);
    assert_values_close(&result.plots[25].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[26].values, &[-1.5, -1.5]);
    assert_values_close(&result.plots[27].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[28].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[29].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[30].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[31].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[32].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[33].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[34].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[35].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[36].values, &[1.0, 1.0]);
}

#[test]
fn selects_nth_array_min_and_max_values() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("nth array min/max")
ints = array.new_int()
ints.push(9007199254740993)
ints.push(na)
ints.push(9007199254740992)
ints.push(9007199254740994)
ints.push(9007199254740993)
plot(array.min(ints))
plot(ints.min(1))
plot(array.min(ints, 2))
plot(array.min(nth=2, id=ints))
plot(ints.max())
plot(array.max(ints, 1))
plot(ints.max(2))
plot(array.max(ints, 3))
plot(array.max(nth=0, id=ints))
plot(ints.min(bar_index))
missing_nth = int(na)
plot(na(array.min(ints, missing_nth)) and na(ints.max(-1)) and na(array.min(ints, 4)) and na(ints.max(4)) ? 1 : 0)

floats = array.new_float()
floats.push(2.5)
floats.push(na)
floats.push(-1.25)
floats.push(2.5)
floats.push(0.5)
plot(floats.min())
plot(array.min(floats, 1))
plot(floats.max(1))
plot(array.max(floats, 2))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 15);
    assert_eq!(
        result.plots[0].values,
        vec![PineValue::Int(9_007_199_254_740_992); 3]
    );
    assert_eq!(
        result.plots[1].values,
        vec![PineValue::Int(9_007_199_254_740_993); 3]
    );
    assert_eq!(
        result.plots[2].values,
        vec![PineValue::Int(9_007_199_254_740_993); 3]
    );
    assert_eq!(
        result.plots[3].values,
        vec![PineValue::Int(9_007_199_254_740_993); 3]
    );
    assert_eq!(
        result.plots[4].values,
        vec![PineValue::Int(9_007_199_254_740_994); 3]
    );
    assert_eq!(
        result.plots[5].values,
        vec![PineValue::Int(9_007_199_254_740_993); 3]
    );
    assert_eq!(
        result.plots[6].values,
        vec![PineValue::Int(9_007_199_254_740_993); 3]
    );
    assert_eq!(
        result.plots[7].values,
        vec![PineValue::Int(9_007_199_254_740_992); 3]
    );
    assert_eq!(
        result.plots[8].values,
        vec![PineValue::Int(9_007_199_254_740_994); 3]
    );
    assert_eq!(
        result.plots[9].values,
        vec![
            PineValue::Int(9_007_199_254_740_992),
            PineValue::Int(9_007_199_254_740_993),
            PineValue::Int(9_007_199_254_740_993),
        ]
    );
    assert_values_close(&result.plots[10].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[-1.25, -1.25, -1.25]);
    assert_values_close(&result.plots[12].values, &[0.5, 0.5, 0.5]);
    assert_values_close(&result.plots[13].values, &[2.5, 2.5, 2.5]);
    assert_values_close(&result.plots[14].values, &[0.5, 0.5, 0.5]);
}

#[test]
fn evaluates_nth_array_min_and_max_arguments_before_reading_array() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("nth array min/max argument evaluation")
positional = array.from(1, 2, 3)
plot(array.min(positional, array.shift(positional)))
plot(positional.size())

reordered = array.from(100, 2, 1)
plot(array.max(nth=array.shift(reordered) * 0 + 1, id=array.copy(reordered)))
plot(reordered.size())

method_values = array.from(1, 2, 3)
plot(method_values.min(array.shift(method_values)))
plot(method_values.size())
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 6);
    assert_values_close(&result.plots[0].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[1].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[4].values, &[3.0, 3.0]);
    assert_values_close(&result.plots[5].values, &[2.0, 2.0]);
}

#[test]
fn runs_array_ordering_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array ordering")
ints = array.new_int()
array.push(ints, 3)
array.push(ints, 1)
array.push(ints, 2)
array.sort(ints)
plot(ints.get(0) * 100 + ints.get(1) * 10 + ints.get(2))
desc_ints = array.from(1, 3, 2)
desc_ints.sort(order.descending)
plot(desc_ints.get(0) * 100 + desc_ints.get(1) * 10 + desc_ints.get(2))
desc_float_special = array.new_float()
desc_float_special.push(na)
desc_float_special.push(close)
desc_float_special.push(high)
desc_float_special.sort(order.descending)
plot(na(desc_float_special.get(0)) and desc_float_special.get(1) == high and desc_float_special.get(2) == close ? 1 : 0)
ints.reverse()
plot(ints.get(0) * 100 + ints.get(1) * 10 + ints.get(2))
unsorted_ints = array.from(30, 10, 20)
sorted_int_indices = unsorted_ints.sort_indices()
plot(sorted_int_indices.get(0) * 100 + sorted_int_indices.get(1) * 10 + sorted_int_indices.get(2))
desc_sorted_int_indices = unsorted_ints.sort_indices(order.descending)
plot(desc_sorted_int_indices.get(0) * 100 + desc_sorted_int_indices.get(1) * 10 + desc_sorted_int_indices.get(2))
plot(unsorted_ints.get(0) * 100 + unsorted_ints.get(1) * 10 + unsorted_ints.get(2))

floats = array.new_float()
floats.push(na)
floats.push(high)
floats.push(close)
floats.sort()
plot(floats.get(0) + floats.get(1))
plot(na(floats.get(2)) ? 1 : 0)
float_indices_source = array.new_float()
float_indices_source.push(na)
float_indices_source.push(high)
float_indices_source.push(close)
float_indices = array.sort_indices(float_indices_source)
plot(float_indices.get(0) * 100 + float_indices.get(1) * 10 + float_indices.get(2))
array.reverse(floats)
plot(na(floats.get(0)) and floats.get(1) == high and floats.get(2) == close ? 1 : 0)

words = array.new_string()
words.push("b")
words.push("a")
words.push("c")
words.push("")
array.sort(words)
plot(words.get(0) == "a" and words.get(1) == "b" and words.get(2) == "c" and words.get(3) == "" ? 1 : 0)
words.sort(order.descending)
plot(words.get(0) == "" and words.get(1) == "c" and words.get(2) == "b" and words.get(3) == "a" ? 1 : 0)
word_indices = words.sort_indices(order.ascending)
plot(word_indices.get(0) == 3 and word_indices.get(1) == 2 and word_indices.get(2) == 1 and word_indices.get(3) == 0 ? 1 : 0)
words.reverse()
plot(words.get(0) == "a" and words.get(1) == "b" and words.get(2) == "c" and words.get(3) == "" ? 1 : 0)

flags = array.from(true, false, false)
flags.reverse()
plot(not flags.get(0) and not flags.get(1) and flags.get(2) ? 1 : 0)
empty_flags = array.new_bool()
empty_flags.reverse()
plot(empty_flags.size())

empty_int_sort = array.new_int()
empty_int_sort.sort()
empty_int_indices = array.sort_indices(empty_int_sort)
plot(empty_int_sort.size())
plot(empty_int_indices.size())
empty_int_sort.reverse()
plot(empty_int_sort.size())

empty_sort = array.new_float()
array.sort(empty_sort)
plot(empty_sort.size())
empty_sort_indices = empty_sort.sort_indices()
plot(empty_sort_indices.size())
empty_sort.reverse()
plot(empty_sort.size())
empty_string_sort = array.new_string()
empty_string_sort.sort()
empty_string_indices = array.sort_indices(empty_string_sort)
plot(empty_string_sort.size() == 0 and empty_string_indices.size() == 0 ? 1 : 0)
empty_string_sort.reverse()
plot(empty_string_sort.size())

colors = array.new_color()
colors.push(color.red)
colors.push(color.green)
colors.reverse()
plot(colors.get(0) == color.green and colors.get(1) == color.red ? 1 : 0)
empty_colors = array.new_color()
empty_colors.reverse()
plot(empty_colors.size())
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 4.0, 0.0, 2.0), bar_ohlc(2.0, 6.0, 1.0, 3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 27);
    assert_values_close(&result.plots[0].values, &[123.0, 123.0]);
    assert_values_close(&result.plots[1].values, &[321.0, 321.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[3].values, &[321.0, 321.0]);
    assert_values_close(&result.plots[4].values, &[120.0, 120.0]);
    assert_values_close(&result.plots[5].values, &[21.0, 21.0]);
    assert_values_close(&result.plots[6].values, &[3120.0, 3120.0]);
    assert_values_close(&result.plots[7].values, &[6.0, 9.0]);
    assert_values_close(&result.plots[8].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[9].values, &[210.0, 210.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[12].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[13].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[14].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[15].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[16].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[17].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[18].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[19].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[20].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[21].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[22].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[23].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[24].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[25].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[26].values, &[0.0, 0.0]);
}

#[test]
fn runs_array_join_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array join")
ints = array.new_int()
ints.push(1)
ints.push(2)
plot(array.join(ints, "|") == "1|2" ? 1 : 0)

floats = array.new_float()
floats.push(1.25)
floats.push(2.5)
plot(floats.join() == "1.25,2.5" ? 1 : 0)
floats.push(na)
plot(array.join(floats, "|") == "1.25|2.5|NaN" ? 1 : 0)

flags = array.new_bool()
flags.push(false)
flags.push(true)
plot(array.join(flags, "/") == "false/true" ? 1 : 0)

words = array.new_string()
words.push("a")
words.push("b")
plot(words.join("-") == "a-b" ? 1 : 0)
plot(words.join(na) == "a,b" ? 1 : 0)
words.insert(1, "")
plot(words.join("|") == "a||b" ? 1 : 0)

colors = array.new_color()
colors.push(color.red)
colors.push(color.green)
plot(colors.join("|") == "15873605|5025616" ? 1 : 0)

empty = array.new_string()
plot(array.join(empty, "|") == "" ? 1 : 0)
empty_ints = array.new_int()
plot(empty_ints.join("|") == "" ? 1 : 0)
empty_floats = array.new_float()
plot(array.join(empty_floats, "|") == "" ? 1 : 0)
empty_flags = array.new_bool()
plot(empty_flags.join("|") == "" ? 1 : 0)
empty_colors = array.new_color()
plot(array.join(empty_colors, "|") == "" ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar_ohlc(1.0, 4.0, 0.0, 2.0), bar_ohlc(2.0, 6.0, 1.0, 3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 13);
    for plot in &result.plots {
        assert_values_close(&plot.values, &[1.0, 1.0]);
    }
}

#[test]
fn rejects_oversized_array_join_result() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array join limit")
values = array.new_string(410)
array.set(values, 0, str.repeat("x", 100))
plot(str.length(array.join(values, str.repeat("y", 100))))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array.join limit error");

    assert!(
        error
            .message
            .contains("array.join result cannot exceed 40960 characters"),
        "{}",
        error.message
    );
}

#[test]
fn runs_array_slice_concat_operations() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array slice concat")
ints = array.new_int()
ints.push(1)
ints.push(2)
ints.push(3)
part = array.slice(ints, 1, 3)
part.set(0, 20)
plot(part.size())
plot(part.get(0) + part.get(1))
plot(ints.get(1))

more = array.new_int()
more.push(4)
returned = array.concat(ints, more)
plot(array.size(ints))
plot(array.size(returned))
plot(returned.get(3))
empty_more = array.new_int()
ints.concat(empty_more)
plot(returned.size() == 4 and ints.size() == 4 and empty_more.size() == 0 ? 1 : 0)
empty_int_target = array.new_int()
empty_int_target.concat(more)
plot(empty_int_target.size() == 1 and empty_int_target.get(0) == 4 and more.size() == 1 ? 1 : 0)

words = array.new_string()
words.push("a")
words.push("b")
words.push("c")
tail = words.slice(1, 3)
extra = array.new_string()
extra.push("d")
words.concat(extra)
plot(tail.join("|") == "b|c" and words.join("|") == "a|b|c|d" ? 1 : 0)
empty_extra = array.new_string()
words.concat(empty_extra)
plot(words.join("|") == "a|b|c|d" and empty_extra.size() == 0 ? 1 : 0)
empty_target = array.new_string()
empty_target.concat(extra)
plot(empty_target.join("|") == "d" and extra.size() == 1 ? 1 : 0)

colors = array.new_color()
colors.push(color.red)
colors.push(color.green)
colors_tail = colors.slice(1, 2)
colors.concat(colors_tail)
plot(colors.get(2) == color.green ? 1 : 0)
empty_colors_tail = array.new_color()
colors.concat(empty_colors_tail)
plot(colors.size() == 3 and empty_colors_tail.size() == 0 ? 1 : 0)
empty_color_target = array.new_color()
empty_color_target.concat(colors_tail)
plot(empty_color_target.size() == 1 and empty_color_target.get(0) == color.green and colors_tail.size() == 1 ? 1 : 0)

floats = array.new_float()
floats.push(close)
floats.push(na)
floats.push(high)
float_head = array.slice(floats, 0, 2)
plot(float_head.size())
plot(float_head.get(0) == close and na(float_head.get(1)) ? 1 : 0)
float_more = array.from(na, high)
float_returned = floats.concat(float_more)
plot(float_returned.size() == 5 and floats.size() == 5 and na(floats.get(3)) and floats.get(4) == high and float_more.size() == 2 ? 1 : 0)
empty_float_more = array.new_float()
floats.concat(empty_float_more)
plot(float_returned.size() == 5 and floats.size() == 5 and empty_float_more.size() == 0 ? 1 : 0)
empty_float_target = array.new_float()
empty_float_target.concat(float_more)
plot(empty_float_target.size() == 2 and na(empty_float_target.get(0)) and empty_float_target.get(1) == high and float_more.size() == 2 ? 1 : 0)

flags = array.from(true, false, true)
flag_tail = flags.slice(1, 3)
flag_tail.set(0, true)
plot(flag_tail.size())
plot(flag_tail.get(0) and flag_tail.get(1) and flags.get(1) ? 1 : 0)
bool_more = array.from(false)
flags.concat(bool_more)
plot(flags.size() == 4 and not flags.get(3) and bool_more.size() == 1 ? 1 : 0)
empty_bool_more = array.new_bool()
flags.concat(empty_bool_more)
plot(flags.size() == 4 and empty_bool_more.size() == 0 ? 1 : 0)
empty_bool_target = array.new_bool()
empty_bool_target.concat(bool_more)
plot(empty_bool_target.size() == 1 and not empty_bool_target.get(0) and bool_more.size() == 1 ? 1 : 0)

empty_window = ints.slice(2, 2)
plot(empty_window.size())
plot(na(array.slice(ints, -1, 1)) and na(ints.slice(1, 5)) and na(array.slice(ints, 2, 1)) ? 1 : 0)

window_source = array.from(0, 1, 2, 3)
window = window_source.slice(0, 3)
window_source.remove(0)
window.push(4)
plot(window.size() * 1000 + window_source.size() * 100 + window.get(0) * 10 + window_source.get(3))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 27);
    assert_values_close(&result.plots[0].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[1].values, &[23.0, 23.0]);
    assert_values_close(&result.plots[2].values, &[20.0, 20.0]);
    assert_values_close(&result.plots[3].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[4].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[5].values, &[4.0, 4.0]);
    assert_values_close(&result.plots[6].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[7].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[8].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[9].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[10].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[11].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[12].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[13].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[14].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[15].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[16].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[17].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[18].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[19].values, &[2.0, 2.0]);
    assert_values_close(&result.plots[20].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[21].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[22].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[23].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[24].values, &[0.0, 0.0]);
    assert_values_close(&result.plots[25].values, &[1.0, 1.0]);
    assert_values_close(&result.plots[26].values, &[4414.0, 4414.0]);
}

#[test]
fn handles_invalid_array_slice_bounds() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array slice bounds")
values = array.new_int()
values.push(1)
plot(na(array.slice(values, -1, 1)) ? 1 : 0)
plot(na(values.slice(1, 3)) ? 1 : 0)
plot(na(array.slice(values, 1, 0)) ? 1 : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[1.0]);
    assert_values_close(&result.plots[1].values, &[1.0]);
    assert_values_close(&result.plots[2].values, &[1.0]);
}

#[test]
fn rejects_oversized_array_concat_result() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array concat limit")
left = array.new_int(100000, 1)
right = array.new_int(1, 2)
array.concat(left, right)
plot(array.size(left))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array.concat limit error");

    assert!(
        error
            .message
            .contains("array.concat cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_oversized_array_insert_result() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array insert limit")
values = array.new_int(100000, 1)
array.insert(values, 0, 2)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array.insert limit error");

    assert!(
        error
            .message
            .contains("array.insert cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn var_float_array_persists_across_bars() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("var array")
var values = array.new_float()
fresh = array.new_float()
array.push(values, close)
array.push(fresh, close)
plot(array.size(values))
plot(array.size(fresh))
plot(array.get(values, 0))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 3);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
    assert_values_close(&result.plots[1].values, &[1.0, 1.0, 1.0]);
    assert_values_close(&result.plots[2].values, &[1.0, 1.0, 1.0]);
}

#[test]
fn handles_float_array_edge_cases() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array edges")
values = array.new_float()
popped = array.pop(values)
plot(na(popped) ? 1 : 0)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let result = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)]).expect("runtime result");

    assert_eq!(result.plots.len(), 2);
    assert_values_close(&result.plots[0].values, &[1.0]);
    assert_values_close(&result.plots[1].values, &[0.0]);
}

fn assert_array_bounds_error(source: &str, expected: &str) {
    let source = SourceFile::new("test.pine", source);
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array bounds error");
    assert!(
        error.message.contains(expected),
        "expected {expected:?} in {:?}",
        error.message
    );
}

#[test]
fn rejects_array_get_out_of_bounds_indexes() {
    assert_array_bounds_error(
        r#"indicator("array get positive bounds")
values = array.from(10, 20, 30)
plot(array.get(values, 3))
"#,
        "array index 3 is out of bounds for array of size 3",
    );
    assert_array_bounds_error(
        r#"indicator("array get negative bounds")
values = array.from(10, 20, 30)
plot(array.get(values, -4))
"#,
        "array index -4 is out of bounds for array of size 3",
    );
}

#[test]
fn rejects_udt_array_call_result_get_out_of_bounds_indexes() {
    assert_array_bounds_error(
        r#"//@version=6
indicator("UDT call-result get empty bounds")
type Point
    float x
type Anchor
    int tag
method values(Anchor self) => array.new<Point>()
anchor = Anchor.new(1)
item = anchor.values().get(0)
plot(item.x)
"#,
        "array index 0 is out of bounds for array of size 0",
    );
    assert_array_bounds_error(
        r#"//@version=6
indicator("UDT call-result get negative bounds")
type Point
    float x
type Anchor
    int tag
method values(Anchor self) => array.from(Point.new(10.0))
anchor = Anchor.new(1)
item = anchor.values().get(-2)
plot(item.x)
"#,
        "array index -2 is out of bounds for array of size 1",
    );
}

#[test]
fn rejects_array_mutation_out_of_bounds_indexes() {
    assert_array_bounds_error(
        r#"indicator("array set bounds")
values = array.from(10, 20, 30)
array.set(values, 3, 40)
"#,
        "array index 3 is out of bounds for array of size 3",
    );
    assert_array_bounds_error(
        r#"indicator("array insert bounds")
values = array.from(10, 20, 30)
array.insert(values, 4, 40)
"#,
        "array index 4 is out of bounds for array of size 3",
    );
    assert_array_bounds_error(
        r#"indicator("array remove bounds")
values = array.from(10, 20, 30)
plot(array.remove(values, -4))
"#,
        "array index -4 is out of bounds for array of size 3",
    );
    assert_array_bounds_error(
        r#"indicator("array remove empty bounds")
values = array.new_float()
plot(array.remove(values, 0))
"#,
        "array index 0 is out of bounds for array of size 0",
    );
    assert_array_bounds_error(
        r#"indicator("array call-result remove bounds")
plot(array.from(10, 20, 30).remove(3))
"#,
        "array index 3 is out of bounds for array of size 3",
    );
    assert_array_bounds_error(
        r#"indicator("array call-result insert bounds")
array.from(10, 20, 30).insert(4, 40)
"#,
        "array index 4 is out of bounds for array of size 3",
    );
    assert_array_bounds_error(
        r#"indicator("array call-result set bounds")
array.from(10, 20, 30).set(3, 40)
"#,
        "array index 3 is out of bounds for array of size 3",
    );
}

#[test]
fn rejects_negative_float_array_size() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array negative size")
values = array.new_float(-1)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected negative array size error");

    assert!(
        error
            .message
            .contains("array.new_float size cannot be negative"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_oversized_float_array_creation() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array oversized")
values = array.new_float(100001)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected oversized array error");

    assert!(
        error
            .message
            .contains("array.new_float size cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_float_array_push_past_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array push limit")
values = array.new_float(100000)
array.push(values, close)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array push limit error");

    assert!(
        error
            .message
            .contains("array.push cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_float_array_call_result_push_past_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array call-result push limit")
array.new_float(100000).push(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array call-result push limit error");

    assert!(
        error
            .message
            .contains("array.push cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_float_array_unshift_past_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array unshift limit")
values = array.new_float(100000)
array.unshift(values, close)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array unshift limit error");

    assert!(
        error
            .message
            .contains("array.unshift cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_float_array_call_result_unshift_past_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array call-result unshift limit")
array.new_float(100000).unshift(close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array call-result unshift limit error");

    assert!(
        error
            .message
            .contains("array.unshift cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn rejects_float_array_call_result_insert_past_limit() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array call-result insert limit")
array.new_float(100000).insert(0, close)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let error = run_historical(&analysis.hir.expect("HIR"), &[bar(1.0)])
        .expect_err("expected array call-result insert limit error");

    assert!(
        error
            .message
            .contains("array.insert cannot exceed 100000 elements"),
        "{}",
        error.message
    );
}

#[test]
fn profiles_float_array_storage() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array profile")
var values = array.new_float()
array.push(values, close)
plot(array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let profiled = run_historical_profiled(&analysis.hir.expect("HIR"), &[bar(1.0), bar(2.0)])
        .expect("profiled runtime result");

    assert_eq!(profiled.profile.array_slots, 1);
    assert_eq!(profiled.profile.array_values, 2);
    assert!(profiled.profile.array_value_capacity >= 2);
}

#[test]
fn runs_readonly_float_array_udf_parameter() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("array udf")
first(values) => array.get(values, 0)
var values = array.new_float()
array.push(values, close)
plot(first(values) + array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[2.0, 3.0, 4.0]);
}

#[test]
fn runs_readonly_int_array_udf_parameter() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("int array udf")
first(values) => array.get(values, 0)
var values = array.new_int()
array.push(values, bar_index)
plot(first(values) + array.size(values))
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn runs_readonly_bool_array_udf_parameter() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("bool array udf")
first(values) => array.get(values, 0)
var values = array.new_bool()
array.push(values, bar_index == 0)
plot(first(values) ? array.size(values) : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn runs_readonly_string_array_udf_parameter() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("string array udf")
first(values) => array.get(values, 0)
var values = array.new_string()
array.push(values, "seed")
plot(first(values) == "seed" ? array.size(values) : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
}

#[test]
fn runs_readonly_color_array_udf_parameter() {
    let source = SourceFile::new(
        "test.pine",
        r#"indicator("color array udf")
first(values) => array.get(values, 0)
var values = array.new_color()
array.push(values, color.red)
plot(first(values) == color.red ? array.size(values) : 0)
"#,
    );
    let analysis = analyze_source(&source);
    assert!(
        analysis.diagnostics.is_empty(),
        "{:?}",
        analysis.diagnostics
    );

    let bars = vec![bar(1.0), bar(2.0), bar(3.0)];
    let result = run_historical(&analysis.hir.expect("HIR"), &bars).expect("runtime result");

    assert_eq!(result.plots.len(), 1);
    assert_values_close(&result.plots[0].values, &[1.0, 2.0, 3.0]);
}
