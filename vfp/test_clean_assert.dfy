// A tiny file with asserts that aren't needed for verification.
// The cleaner should remove them and the program should still verify.

method Inc(x: int) returns (y: int)
  ensures y > x
{
  y := x + 1;
  assert y == x + 1;          // <-- unnecessary
  assert x + 1 > x;           // <-- unnecessary (obvious arithmetic)
}

method Max2(a: int, b: int) returns (m: int)
  ensures m >= a && m >= b
  ensures m == a || m == b
{
  if a >= b {
    m := a;
    assert m == a;            // <-- unnecessary (just assigned)
  } else {
    m := b;
    assert m == b;            // <-- unnecessary
  }
}
