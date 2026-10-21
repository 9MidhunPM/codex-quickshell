import QtQuick
import QtTest
import "../StatusFormat.js" as Format

TestCase {
    name: "StatusFormat"

    function test_credits_data() {
        return [
            {tag: "scientific_zero", value: {balance: "0E-10"}, expected: "0"},
            {tag: "padded_scientific_zero", value: {balance: " 0E-10 "}, expected: "0"},
            {tag: "trailing_point_zero", value: {balance: "0.E-10"}, expected: "0"},
            {tag: "leading_point_zero", value: {balance: ".0E-10"}, expected: "0"},
            {tag: "negative_scientific_zero", value: {balance: "-0.000E-10"}, expected: "0"},
            {tag: "number_zero", value: {balance: 0, hasCredits: false}, expected: "0"},
            {tag: "small_nonzero", value: {balance: "1E-10"}, expected: "0.0000000001"},
            {tag: "unknown", value: null, expected: "Unavailable"},
            {tag: "unknown_balance", value: {balance: null}, expected: "Unavailable"},
            {tag: "unlimited", value: {balance: null, unlimited: true}, expected: "Unlimited"},
            {tag: "no_credits", value: {balance: null, hasCredits: false}, expected: "No credits"},
            {tag: "unknown_amount", value: {balance: null, hasCredits: true},
                expected: "Available · amount unavailable"},
            {tag: "extreme_negative_exponent", value: {balance: "1e-1000"}, expected: "See details"},
            {tag: "extreme_positive_exponent", value: {balance: "1e1000"}, expected: "See details"},
            {tag: "precise_fraction", value: {balance: "0.123456789012345678901234567890"},
                expected: "0.12345678901234567890123456789"},
            {tag: "precise_scientific_fraction", value: {balance: "1.2345678901234567890123456789e-10"},
                expected: "0.00000000012345678901234567890123456789"},
            {tag: "precise_large_integer", value: {balance: "123456789012345678901234567890e0"},
                expected: "123456789012345678901234567890"}
        ];
    }

    function test_credits(data) {
        compare(Format.credits(data.value), data.expected);
    }

    function test_scientific_expansion_limit() {
        var smallLimit = "0." + new Array(62).join("0") + "1";
        var largeLimit = "1" + new Array(64).join("0");
        compare(smallLimit.length, 64);
        compare(largeLimit.length, 64);
        compare(Format.credits({balance: "1e-62"}), smallLimit);
        compare(Format.credits({balance: "1e63"}), largeLimit);
        compare(Format.credits({balance: "1e-63"}), "See details");
        compare(Format.credits({balance: "1e64"}), "See details");
    }

    function test_extreme_values_retain_raw_detail() {
        compare(Format.creditDetail({balance: "1e-1000"}), "1e-1000");
        compare(Format.creditDetail({balance: "1e1000"}), "1e1000");
        compare(Format.creditDetail({balance: "1.2345678901234567890123456789e-1000"}),
            "1.2345678901234567890123456789e-1000");
    }

    function test_long_mantissa_is_normalized_exactly() {
        var balance = "1" + new Array(80).join("0") + "e-80";
        compare(Format.credits({balance: balance}), "0.1");
    }

    function test_long_tiny_balance_retains_raw_detail() {
        var balance = "0." + new Array(99).join("0") + "1";
        compare(balance.length, 101);
        compare(Format.credits({balance: balance}), "See details");
        compare(Format.creditDetail({balance: balance}), balance);
    }

    function test_raw_balance_display_limit() {
        var limit = "0." + new Array(254).join("0") + "1";
        compare(limit.length, 256);
        compare(Format.credits({balance: limit}), "See details");
        compare(Format.creditDetail({balance: limit}), limit);

        var overLimit = "0." + new Array(255).join("0") + "1";
        compare(overLimit.length, 257);
        compare(Format.credits({balance: overLimit}), "See details");
        compare(Format.creditDetail({balance: overLimit}),
            "Provider value exceeds display limit.");

        var projectedLimit = {balance: null, balanceTruncated: true, hasCredits: false};
        compare(Format.credits(projectedLimit), "See details");
        compare(Format.creditDetail(projectedLimit),
            "Provider value exceeds display limit.");
    }
}
