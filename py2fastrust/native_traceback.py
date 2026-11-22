"""Traceback frame lines as printed by traceback.StackSummary.format (Lib/traceback.py, 3.14).

A run of more than three identical (file, line, function) frames prints the
first three and then "  [Previous line repeated N more time(s)]", which is how
CPython shortens deep recursion. Source-line excerpts are not printed.
"""


def print_frames(frames, origin=None, *, optional=False):
    """Rust statements printing ``frames`` (an iterator of (&str,usize,&str), outermost first)
    followed by ``origin``: one such tuple expression, or an Option of one when ``optional``."""
    if origin is None:
        chain = frames
    else:
        chain = frames + ('.chain(' + origin + ')' if optional else '.chain(std::iter::once(' + origin + '))')
    repeat = ('{let native_more=native_count-3;eprintln!("  [Previous line repeated {} more time{}]",'
              'native_more,if native_more>1{"s"}else{""});}')
    return ('{let mut native_last:Option<(&str,usize,&str)>=None;let mut native_count=0_usize;'
            'for native_frame in ' + chain + '{let native_frame:(&str,usize,&str)=native_frame;'
            'if native_last!=Some(native_frame){if native_count>3' + repeat + 'native_last=Some(native_frame);native_count=0;}'
            'native_count+=1;if native_count>3{continue;}'
            'eprintln!("  File {:?}, line {}, in {}",native_frame.0,native_frame.1,native_frame.2);}'
            'if native_count>3' + repeat + '}')
