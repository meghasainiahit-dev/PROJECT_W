import 'package:stockos_mobile/main.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('StockOS default URL is configured', () {
    expect(stockOsUrl, isNotEmpty);
    expect(Uri.parse(stockOsUrl).hasScheme, isTrue);
  });
}
