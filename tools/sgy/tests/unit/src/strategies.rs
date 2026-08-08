use proptest::{collection, prelude::*, strategy::BoxedStrategy};
use serde_json::{Map, Number, Value};

pub fn unicode_string(max_chars: usize) -> BoxedStrategy<String> {
    collection::vec(any::<char>(), 0..=max_chars)
        .prop_map(|characters| characters.into_iter().collect())
        .boxed()
}

pub fn json_value() -> BoxedStrategy<Value> {
    let leaf = prop_oneof![
        Just(Value::Null),
        any::<bool>().prop_map(Value::Bool),
        any::<i64>().prop_map(|value| Value::Number(Number::from(value))),
        any::<u64>().prop_map(|value| Value::Number(Number::from(value))),
        unicode_string(32).prop_map(Value::String),
    ];

    leaf.prop_recursive(6, 192, 8, |inner| {
        prop_oneof![
            collection::vec(inner.clone(), 0..8).prop_map(Value::Array),
            collection::btree_map(unicode_string(16), inner, 0..8).prop_map(|entries| {
                Value::Object(entries.into_iter().collect::<Map<String, Value>>())
            }),
        ]
    })
    .boxed()
}

pub fn argv_token() -> BoxedStrategy<String> {
    unicode_string(24)
}

pub fn valid_field_name() -> BoxedStrategy<String> {
    collection::vec(
        prop_oneof![
            proptest::char::range('a', 'z'),
            proptest::char::range('A', 'Z'),
            proptest::char::range('0', '9'),
            Just('_'),
            Just('-'),
        ],
        1..16,
    )
    .prop_map(|characters| characters.into_iter().collect())
    .boxed()
}
