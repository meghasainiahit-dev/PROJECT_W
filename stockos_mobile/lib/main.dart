import 'dart:io';

import 'package:flutter/material.dart';
import 'package:webview_flutter/webview_flutter.dart';

const String stockOsUrl = String.fromEnvironment(
  'STOCKOS_URL',
  defaultValue: 'https://ab5b-103-87-58-100.ngrok-free.app/dashboard/',
);

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const StockOsApp());
}

class StockOsApp extends StatelessWidget {
  const StockOsApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'StockOS',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF211D63)),
        useMaterial3: true,
      ),
      home: const StockOsWebView(),
    );
  }
}

class StockOsWebView extends StatefulWidget {
  const StockOsWebView({super.key});

  @override
  State<StockOsWebView> createState() => _StockOsWebViewState();
}

class _StockOsWebViewState extends State<StockOsWebView> {
  late final WebViewController _controller;
  int _progress = 0;
  bool _hasError = false;
  String _errorText = '';

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setBackgroundColor(Colors.white)
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (progress) {
            setState(() {
              _progress = progress;
              _hasError = false;
            });
          },
          onPageFinished: (_) => setState(() => _progress = 100),
          onWebResourceError: (error) {
            if (error.isForMainFrame == true) {
              setState(() {
                _hasError = true;
                _errorText = error.description;
              });
            }
          },
        ),
      )
      ..loadRequest(Uri.parse(stockOsUrl));
  }

  Future<bool> _handleBack() async {
    if (await _controller.canGoBack()) {
      await _controller.goBack();
      return false;
    }
    return true;
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        final shouldPop = await _handleBack();
        if (shouldPop && context.mounted) {
          Navigator.of(context).maybePop();
        }
      },
      child: Scaffold(
        backgroundColor: Colors.white,
        body: SafeArea(
          child: Stack(
            children: [
              WebViewWidget(controller: _controller),
              if (_progress < 100)
                LinearProgressIndicator(
                  value: _progress / 100,
                  minHeight: 2,
                  color: const Color(0xFF211D63),
                  backgroundColor: const Color(0xFFE8E7EE),
                ),
              if (_hasError)
                _ErrorOverlay(
                  message: _errorText,
                  onRetry: () {
                    setState(() {
                      _hasError = false;
                      _progress = 0;
                    });
                    _controller.reload();
                  },
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ErrorOverlay extends StatelessWidget {
  const _ErrorOverlay({
    required this.message,
    required this.onRetry,
  });

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.all(24),
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(
              Icons.wifi_off_rounded,
              size: 48,
              color: Color(0xFF211D63),
            ),
            const SizedBox(height: 16),
            const Text(
              'StockOS load nahi ho paaya',
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 18,
                fontWeight: FontWeight.w700,
                color: Color(0xFF18163D),
              ),
            ),
            const SizedBox(height: 8),
            Text(
              _friendlyMessage(message),
              textAlign: TextAlign.center,
              style: const TextStyle(
                fontSize: 13,
                color: Color(0xFF777583),
              ),
            ),
            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('Retry'),
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFF211D63),
                foregroundColor: Colors.white,
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _friendlyMessage(String message) {
    final target = Platform.isAndroid ? '10.0.2.2:8000' : 'localhost:8000';
    if (message.trim().isEmpty) {
      return 'Django server running hai ya nahi check karo. Target: $target';
    }
    return '$message\n\nDjango server running hai ya nahi check karo. Target: $target';
  }
}
