import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:flutter_audio_capture/flutter_audio_capture.dart';
import 'package:permission_handler/permission_handler.dart';

void main() {
  // Indispensable pour que les plugins fonctionnent avant runApp.
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const TranscribeApp());
}

class TranscribeApp extends StatelessWidget {
  const TranscribeApp({super.key});
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Transcription en direct',
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.blue),
      ),
      home: const LiveTranscriptionScreen(),
    );
  }
}

class LiveTranscriptionScreen extends StatefulWidget {
  const LiveTranscriptionScreen({super.key});

  @override
  State<LiveTranscriptionScreen> createState() =>
      _LiveTranscriptionScreenState();
}

class _LiveTranscriptionScreenState extends State<LiveTranscriptionScreen> {
  // Adresse du serveur Live (ngrok ou IP locale)
  final String _serverUrl = 'ws://192.168.19.53:6000/ws/transcribe';
  WebSocketChannel? _channel;
  late final FlutterAudioCapture _recorder;

  String _statusMessage = '';
  String _fullTranscription = '';
  bool _isConnected = false;
  bool _isRecording = false;
  final ScrollController _scrollController = ScrollController();

  @override
  void initState() {
    super.initState();
    _recorder = FlutterAudioCapture();
    _connect();
  }

  /* ---------- WebSocket ---------- */
  Future<void> _connect() async {
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_serverUrl));
      await _channel!.ready;
      setState(() {
        _isConnected = true;
        _statusMessage = 'Connecté';
      });

      _channel!.stream.listen(
        (text) {
          setState(() {
            _fullTranscription += text;
          });
          _scrollToBottom();
        },
        onError: (e) {
          setState(() {
            _statusMessage = 'Erreur WebSocket : $e';
            _isConnected = false;
          });
        },
        onDone: () {
          setState(() {
            _statusMessage = 'Connexion fermée';
            _isConnected = false;
          });
        },
      );
    } catch (e) {
      setState(() {
        _statusMessage = 'Impossible de se connecter : $e';
      });
    }
  }

  /* ---------- Micro ---------- */
  Future<void> _toggleRecording() async {
    if (!_isConnected) return;

    if (!_isRecording) {
      final status = await Permission.microphone.request();
      if (status != PermissionStatus.granted) {
        setState(() => _statusMessage = 'Permission micro refusée');
        return;
      }

      await _recorder.init();
      await _recorder.start(
        _onAudio,
        (e) => setState(() => _statusMessage = 'Erreur audio : $e'),
        sampleRate: 16000,
        bufferSize: 1024,
      );
      setState(() {
        _isRecording = true;
        _statusMessage = 'Enregistrement…';
      });
    } else {
      await _recorder.stop();
      setState(() {
        _isRecording = false;
        _statusMessage = 'Arrêté';
      });
    }
  }

  void _onAudio(dynamic data) {
    if (data is! Float64List) return;
    final pcm = Int16List.fromList(
      data.map((f) => (f * 32767).clamp(-32768, 32767).toInt()).toList(),
    );
    _channel?.sink.add(Uint8List.view(pcm.buffer));
  }

  /* ---------- UI ---------- */
  void _scrollToBottom() => WidgetsBinding.instance.addPostFrameCallback(
    (_) => _scrollController.animateTo(
      _scrollController.position.maxScrollExtent,
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOut,
    ),
  );

  void _clear() => setState(() => _fullTranscription = '');

  @override
  void dispose() {
    _recorder.stop();
    _channel?.sink.close();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    print(_statusMessage);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Live'),
        actions: [
          if (_fullTranscription.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.clear),
              onPressed: _clear,
              tooltip: 'Effacer',
            ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          children: [
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _isRecording ? Colors.green : Colors.grey,
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                _statusMessage,
                textAlign: TextAlign.center,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),

            const SizedBox(height: 16),
            Expanded(
              child: SingleChildScrollView(
                controller: _scrollController,
                child: Text(
                  _fullTranscription.isEmpty ? 'Parlez…' : _fullTranscription,
                  style: const TextStyle(fontSize: 18),
                ),
              ),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: ElevatedButton.icon(
                    onPressed: _isConnected ? _toggleRecording : null,
                    icon: Icon(_isRecording ? Icons.stop : Icons.mic),
                    label: Text(_isRecording ? 'Arrêter' : 'Commencer'),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: _isRecording ? Colors.red : Colors.blue,
                      padding: const EdgeInsets.symmetric(vertical: 16),
                    ),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
