# Histórico de versões

## 1.5.0

- **Nova versão para macOS** (Apple Silicon, macOS 15 ou mais novo), distribuída em `.dmg`: gravação da tela inteira e de região pelo AVFoundation, codificação por GPU (VideoToolbox), microfone e áudio em AAC nativo, atalhos globais, efeitos de clique e de teclas, barra, lupa e moldura do zoom fora do vídeo, webcam e envio ao editor de vídeo.
- No Mac, o som do sistema é gravado por um dispositivo de áudio virtual (por exemplo, o BlackHole), que aparece automaticamente como opção.
- As atualizações pelo GitHub também valem no Mac: o programa baixa o `.dmg`, confere o SHA-256 e abre a imagem para a substituição.

## 1.4.0

- **Editores instalados por Snap agora são encontrados** (por exemplo, o OpenShot no Manjaro/Arch, que fica fora do PATH). A busca passou a olhar também Flatpak, AppImage (pastas Applications/AppImages/Downloads) e os atalhos do menu de aplicativos; no macOS, a pasta Aplicativos.
- **Shotcut e OpenShot recebem a gravação já na linha do tempo**, como o Kdenlive: o programa gera o projeto do próprio editor (`.mlt` ou `.osp`) com vídeo e áudio no início da trilha.
- **Escolha do seu editor:** em Configurações › Geral › Editor de vídeo, "Escolher outro editor…" aceita o programa ou o atalho dele (`.desktop`, AppImage, `.exe`, `.lnk` ou `.app`). Se for Kdenlive, Shotcut ou OpenShot, a gravação entra na linha do tempo; outros editores recebem o arquivo de vídeo.

## 1.3.1

- **Windows: as gravações voltaram a ser salvas.** O vídeo era gravado, mas o arquivo ia parar fora da pasta escolhida e o programa avisava "Nada foi gravado". Agora ele é salvo na pasta das gravações, em MP4.
- **Windows: a gravação é enviada ao editor ao terminar.** Com o Kdenlive instalado, ele abre com o vídeo já na linha do tempo.
- **Tema escuro nas listas e menus:** em sistemas com tema claro, as listas das caixas de seleção apareciam com fundo branco e texto ilegível. O programa passa a usar as próprias cores em todas as janelas, sem depender do tema do sistema.
- **Windows testado em uso real** (Windows 11): gravação em tela inteira e por região com microfone e som do sistema, atalhos globais, zoom acompanhando o mouse com moldura e miniatura ao vivo, e envio ao Kdenlive.

## 1.3.0

- **Atualizações pelo GitHub dentro do programa:** em Configurações › Geral › Atualizações, escolha a frequência da verificação ou clique em "Verificar agora". Havendo versão nova, o programa mostra as novidades, baixa o pacote do sistema, confere o SHA-256 e instala.
- **Novos instaladores:** `.deb` (Debian/Ubuntu), `.rpm` (Fedora e compatíveis) e a primeira versão para **Windows**, além do `.pkg.tar.zst` (BigLinux/Manjaro/Arch).
- **Windows:** captura por Direct3D 11, áudio por WASAPI (microfone e som do sistema), atalhos globais, efeitos de clique e de teclas e barra fora do vídeo. Ainda não testada em máquinas reais.
- Licença GPL-3.0-or-later.

## 1.2.0

- **Zoom ao vivo visível para quem grava:** moldura sobre a tela mostrando a área enquadrada e miniatura flutuante com o vídeo já ampliado. Nenhuma das duas entra no vídeo.

## 1.1.0

- **Zoom acompanhando o mouse**, com efeito de pan suave, ligado e ajustado por atalho.
- **Lupa reescrita:** composta direto no vídeo e centrada exatamente no ponteiro; na tela, uma janela própria fora da captura mostra o conteúdo real ao vivo.
- **Áudio:** corrigidos os cortes ("som picotado") ao gravar microfone e som do sistema juntos.
- **Monitores com escala** (por exemplo, 125%) agora são gravados com as coordenadas corretas.
- **Vários monitores:** seleção de área em todos ao mesmo tempo, escolha do monitor para tela inteira e autorização de captura lembrada por monitor.
- **Barra de ferramentas:** widget recolhido com alça de arraste, nome e atalho de cada item ao passar o mouse.
- Ao enviar a gravação ao editor, o gravador se encerra para evitar gravações acidentais.

## 1.0.0

- Primeira versão: gravação de tela inteira, janela ou região, com contagem regressiva, pausa e retomada.
- Microfone e som do sistema, com medidor e teste de microfone.
- Anotações em tempo real: caneta, marca-texto, seta, linha, retângulo, elipse, texto e desfoque.
- Efeitos do mouse: clique, destaque, holofote, lupa e combinações de teclas animadas.
- Webcam flutuante em vários formatos.
- Atalhos globais personalizáveis.
- Envio automático da gravação ao Kdenlive, já na linha do tempo.
