import pytest

from wow_eye import savedvars


def test_parses_client_format():
    text = r'''
Blank = nil
Db = {
["version"] = 3,
["height"] = 300.0000610351563,
["big"] = 1e+15,
["neg"] = -2,
["on"] = true,
["off"] = false,
["quote"] = "say \"hi\"\nthere \\ ok",
["list"] = {
"a", -- [1]
nil, -- [2]
{
["x"] = 1,
}, -- [3]
},
[42] = "sparse",
["empty"] = {
},
["inf"] = math.huge,
}
'''
    data = savedvars.loads(text)
    assert data["Blank"] is None
    db = data["Db"]
    assert db["version"] == 3
    assert db["height"] == 300.0000610351563
    assert db["big"] == 1e15
    assert db["neg"] == -2
    assert db["on"] is True and db["off"] is False
    assert db["quote"] == 'say "hi"\nthere \\ ok'
    assert db["list"] == ["a", None, {"x": 1}]
    assert db[42] == "sparse"
    assert db["empty"] == {}
    assert db["inf"] == float("inf")


def test_utf8_and_byte_escapes(tmp_path):
    path = tmp_path / "x.lua"
    path.write_bytes('A = "café \\195\\169"\n'.encode("utf-8"))
    assert savedvars.load(path)["A"] == "café é"


def test_never_evaluates_code():
    with pytest.raises(savedvars.ParseError):
        savedvars.loads('A = os.execute("calc")')
    with pytest.raises(savedvars.ParseError):
        savedvars.loads("A = (function() end)()")


def test_dump_round_trip():
    value = {"s": 'q"\\\n\x01', "n": [1, 2.5, True, None], "d": {"k": "v"}, 3: "x"}
    text = "A = " + savedvars.dumps_value(value)
    assert savedvars.loads(text)["A"] == value


def test_dump_refuses_what_it_cant_represent():
    with pytest.raises(TypeError):
        savedvars.dumps_value(object())
    with pytest.raises(ValueError):
        savedvars.dumps_value(float("nan"))
